import enum
import threading
import subprocess
import shutil
import queue

class IsolatedJobEnvironment:
    def __init__(self):
        self._instructions = []
        pass

    def add_directory(self, host, virtual):
        self._instructions.append((0, host, virtual))

    def add_file(self, host, virtual):
        self._instructions.append((1, host, virtual))

    def _get_instructions(self):
        return self._instructions

class JobResult(enum.Enum):
    OK = 0
    TL = 1
    TL_SOFT = 2
    RE = 3
    ML = 4
    FL = 5

    """
    FL is for system failure
    
    Please note, that some systems may not support all verdicts (e.g. ML).
    """
    
    def ok(self):
        return self == JobResult.OK
    def complete(self):
        return self in [JobResult.OK, JobResult.TL_SOFT]
    
class SimpleJobLimits:
    def __init__(self):
        self.timelimit = None
        self.timelimit_hard = None
        self.timelimit_wall = None
        self.memorylimit = None
        
    def set_timelimit(self, tm):
        """
        Sets restriction to overall computation time

        Parameters:
        tm, time in milliseconds, as integer.
        """
        self.timelimit = tm

    def set_timelimit_hard(self, tm):
        """
        Sets hard limit on a job
        This way job will be reported as TL'ed, but can still be completed

        Parameters:
        tm, time in milliseconds, as integer.
        """

        self.timelimit_hard = tm

    def set_timelimit_wall(self, tm):
        """
        Sets the real time limit on a job

        Parameters:
        tm, time in milliseconds, as integer.
        """
        self.timelimit_wall = tm

    def set_memorylimit(self, mem):
        """
        Sets the max memory usage

        Parameters:
        mem: memory limit in kb's, as integer.
        """

        self.memory_limit = mem

class IsolatedJob:
    def __init__(self, judge, env, limits, *command, in_file=None, out_file=None, err_file=None):
        self._judge     = judge
        self._env       = env
        self._limits    = limits
        self._command   = command
        self._in_file   = in_file
        self._out_file  = out_file
        self._err_file  = err_file
        
        self._result         = None
        self._timeusage      = None
        self._wallusage      = None
        self._memusage       = None
        self._failure_reason = None
        
        self._lock     = threading.Lock()
        self._cv       = threading.Condition(lock=self._lock)

    def _init(self, box_id):
        subprocess.check_call(["isolate", "--cleanup", "--cg", "--box-id={}".format(box_id)], timeout=1)
        self._workdir = subprocess.check_output(["isolate", "--init", "--cg", "--box-id={}".format(box_id)], stdout=subprocess.PIPE, timeout=1, universal_newlines=True)

        self._workdir.strip()
        
    def _parse_result(self, isolate_meta):
        def parse_time(value):
            # Probably OK, but TODO
            return int(1000 * float(value))
        
        the_result = None
        for line in isolate_meta.split("\n"):
            (key, value) = line.split(":", maxsplit=1)
            if key == "status":
                the_result = {"OK": JobResult.OK, "TO": JobResult.TL, "RE": JobResult.RE,
                              "XX": JobResult.FL}[value]
            if key == "time":
                self._timeusage = parse_time(value)
            if key == "time-wall":
                self._wallusage = parse_time(value)
            if key == "cg-mem":
                self._memusage  = int(value)

        if the_result == None:
            raise ValueError("Result not provided")
        return the_result
                
    def _run(self, box_id):
        isolate_head = ["isolate", "--run", "--meta=/dev/stdout", "-s", "--cg", "--cg-timing", "--box-id={}".format(box_id)]
        isolate_mid  = []
        isolate_tail = ["--"] + self._command
        
        if self._env:
            for (tp, host, virtual) in self._env._get_instructions():
                if tp == 0: # dir
                    isolate_mid.append("--dir={}:{}".format(host, virtual))
                else:
                    shutil.copyfile(host, os.path.join(self._workdir, virtual))

        if self._limits:
            if self._limits.memorylimit:
                isolate_head.append("--cg-mem={}".format(self._limits.memorylimit))
                
            TL  = self._limits.timelimit
            HTL = self._limits.timelimit_hard
            WTL = self._limits.timelimit_wall
            if HTL and not TL:
                TL = HTL

            def make_time(tm):
                return "%d.%3d" % (tm // 1000, tm % 1000)
            
            if TL:
                isolate_head.append("--time={}".format(make_time(TL)))
            if HTL and HTL != TL:
                isolate_head.append("--extra-time={}".format(make_time(HTL - TL)))
            if WTL:
                isolate_head.append("--wall-time={}".format(make_time(WTL)))        

        os.mkdir(os.path.join(self.work_dir, "files"))
                
        cmd = isolate_head + isolate_mid + isolate_tail
        res = subprocess.run(cmd, stdout=subprocess.PIPE, universal_newlines=True)
        
        if res.returncode not in [0, 1]:
            raise Exception("Isolate returned bad exit code")

        self._result = self._parse_result(res.stdout)
        with self._lock:
            self._cv.notify_all()

    def _clean(self, box_id):
        if self._workdir:
            try:
                subprocess.call(["isolate", "--cleanup", "--cg", "--box-id={}".format(box_id)], timeout=1)
            except ex:
                print("Failed to cleanup: {}".format(ex))

        if self._files_dir:
            self._files_dir.cleanup()
                
    def _work(self, box_id):
        self._box_id = box_id
        
        try:
            self._init(box_id)
            self._run(box_id)
        except Exception as ex:
            self._failure_reason = str(ex)
            self._result = JobResult.FL

    def is_ready(self):
        with self._lock:
            return self._result != None

    def result(self):
        self.wait()
        return self._result

    def time_used(self):
        self.wait()
        return self._timeusage

    def wall_usage(self):
        self.wait()
        return self._wallusage

    def failure_reason(self):
        self.wait()
        return self._failure_reason
                       
    def wait(self):
        if self._result != None:
            return
        
        with self._cv:
            while self._result == None:
                self._cv.wait()

    def release(self):
        """
        Releases job and destroys all result
        """
        
        self._clean(self._box_id)

class IsolatedJudge:
    def __init__(self):
        self._queue = queue.Queue()
        self._thread = threading.Thread(target = IsolatedJudge._work, args = (self,))
        self._thread.start()
        
    def __enter__(self):
        return self

    def __exit__(self, *_):
        print("shutting down judging system")
        self._queue.put(None)
        self._thread.join()

    def _work(self):
        while True:
            job = self._queue.get()
            if job == None:
                return

            job._work()
    
    def new_job(self, env, limits, *command, in_file=None, out_file=None, err_file=None):
        """
        Creates new runnable Job 
        
        Keyword Arguments:
        env: use judge.new_env()
        limits: use judge.new_limits()
        in_file: path to the stdin.
        out_file: path to the stdout.
        err_file: path to the stderr.
        
        Other arguments:
        Specify the command to run in a standard way
        """

        job = IsolatedJob(self, env, limits, *command, in_file=in_file, out_file=out_file, err_file=err_file)

        self._queue.put(job)
        return job
        
    def new_env(self):
        return IsolatedJobEnvironment()

    def new_limits(self):
        return SimpleJobLimits()

def new_judge():
    return IsolatedJudge()
