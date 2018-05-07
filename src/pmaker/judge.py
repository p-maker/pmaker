import enum
import threading
import subprocess
import shutil
import queue
import traceback
import os, os.path

class IsolatedJobEnvironment:
    def __init__(self):
        self._instructions = []
        pass

    def add_directory(self, host, virtual):
        if not virtual.startswith("/"):
            raise ValueError("Please use absolute virtual paths")
        self._instructions.append((0, host, virtual))

    def add_file(self, host, virtual):
        if not virtual.startswith("/"):
            raise ValueError("Please use absolute virtual paths")
        self._instructions.append((1, host, virtual))

    def add_exe_file(self, host, virtual):
        if not virtual.startswith("/"):
            raise ValueError("Please use absolute virtual paths")
        self._instructions.append((2, host, virtual))

        
    def _get_instructions(self):
        return self._instructions

class JobResult(enum.Enum):
    OK = 0
    TL = 1
    RE = 2
    SG = 3
    ML = 4
    FL = 5

    """
    FL is for system failure
    
    Please note, that some systems may not support all verdicts (e.g. ML).
    """
    
    def ok(self):
        return self == JobResult.OK

    def ok_or_re(self):
        return self in [JobResult.OK, JobResult.RE]

class SimpleJobLimits:
    def __init__(self):
        self.timelimit      = None
        self.timelimit_wall = None
        self.memorylimit    = None
        self.proclimit      = 1
        
    def set_timelimit(self, tm):
        """
        Sets restriction to overall computation time

        Parameters:
        tm, time in milliseconds, as integer.
        """
        self.timelimit = tm

    def set_timelimit_wall(self, tm):
        """
        Sets the real time limit on a job

        Parameters:
        tm, time in milliseconds, as integer.
        """
        self.timelimit_wall = tm

    def set_proclimit(self, proc):
        """
        Sets the maximum number of simultaneous processes

        Defaults to 1.
        """
        
        self.proclimit = proc
        
    def set_memorylimit(self, mem):
        """
        Sets the max memory usage

        Parameters:
        mem: memory limit in kb's, as integer.
        """

        self.memory_limit = mem

class IsolatedJob:
    def __init__(self, judge, env, limits, *command, in_file=None, c_handler=None, c_args=None):
        from time import time
        self.__time = time()
        

        self._judge     = judge
        self._env       = env
        self._limits    = limits
        self._command   = list(command)
        self._in_file   = in_file
        self._c_handler = c_handler
        self._c_args    = c_args
        
        self._step = "pending"
        
        self._result         = None
        self._timeusage      = None
        self._wallusage      = None
        self._memusage       = None
        self._failure_reason = None
        
        self._lock     = threading.Lock()
        self._cv       = threading.Condition(lock=self._lock)

        self._workdir  = None
        self._quite    = False
        
        self._exitcode = None
        self._exitsig  = None

    def set_quite(self):
        self.quite = True
    
    def _init(self, box_id):
        subprocess.check_call(["isolate", "--cleanup", "--cg", "--box-id={}".format(box_id)], timeout=10)
        self._workdir = subprocess.check_output(["isolate", "--init", "--cg", "--box-id={}".format(box_id)], timeout=10, universal_newlines=True).strip() + "/box"
        
    def _parse_result(self, isolate_meta):
        def parse_time(value):
            # Probably OK, but TODO
            return int(1000 * float(value))
        
        the_result = None
        for line in isolate_meta.split("\n"):
            if len(line) == 0:
                continue
            
            (key, value) = line.split(":", maxsplit=1)
            if key == "status":
                the_result = {"OK": JobResult.OK, "TO": JobResult.TL, "RE": JobResult.RE,
                              "SG": JobResult.RE, "XX": JobResult.FL}[value]
            if key == "time":
                self._timeusage = parse_time(value)
            if key == "time-wall":
                self._wallusage = parse_time(value)
            if key == "cg-mem":
                self._memusage  = int(value)
            if key == "exitcode":
                self._exitcode  = int(value)
                if self._exitcode == 0:
                    the_result = JobResult.OK
            if key == "exitsig":
                self._exitsig   = value
                the_result = JobResult.SG

        if the_result == None:
            raise ValueError("Result not provided, responce was:\n" + isolate_meta)
        return the_result
                
    def _run(self, box_id):
        isolate_head = ["isolate", "--run", "--meta=/dev/stdout", "-s", "--cg", "--cg-timing", "--box-id={}".format(box_id)]
        isolate_mid  = []
        isolate_tail = ["--"] + self._command
        
        if self._env:
            for (tp, host, virtual) in self._env._get_instructions():
                if tp == 0: # dir
                    isolate_mid.append("--dir={}={}".format(host, virtual))
                elif tp == 1:
                    shutil.copyfile(host, os.path.join(self._workdir, virtual[1:]))
                elif tp == 2:
                    shutil.copyfile(host, os.path.join(self._workdir, virtual[1:]))
                    os.chmod(os.path.join(self._workdir, virtual[1:]), 0o755)

        if self._limits:
            if self._limits.memorylimit:
                isolate_head.append("--cg-mem={}".format(self._limits.memorylimit))
            if self._limits.proclimit:
                isolate_head.append("--processes={}".format(self._limits.proclimit))
                
            TL  = self._limits.timelimit
            WTL = self._limits.timelimit_wall
            def make_time(tm):
                return "%d.%03d" % (tm // 1000, tm % 1000)
            
            if TL:
                isolate_head.append("--time={}".format(make_time(TL)))
            if WTL:
                isolate_head.append("--wall-time={}".format(make_time(WTL)))

        isolate_head.append("--env=PATH=/usr/local/bin:/usr/bin/:/bin")
        os.mkdir(os.path.join(self._workdir, "_files"))
        for fl in ["stdin", "stdout", "stderr"]:
            with open(os.path.join(self._workdir, "_files", fl), "w") as f:
                pass
        
        if self._in_file:
            shutil.copyfile(self._in_file, os.path.join(self._workdir, "_files", "stdin"))

        isolate_head.append( "--stdin={}".format("_files/stdin"))
        isolate_head.append("--stdout={}".format("_files/stdout"))
        isolate_head.append("--stderr={}".format("_files/stderr"))
        
        cmd = isolate_head + isolate_mid + isolate_tail
        
        if not self._quite:
            print(cmd)
        
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
            except Exception as ex:
                print("warning: failed to cleanup: {}".format(ex))

    def _just_fail(self):
        self._failure_reason = "Aborted"
        self._result = JobResult.FL
        with self._lock:
            self._cv.notify_all()
                
    def _work(self, box_id):
        self._box_id = box_id

        try:
            self._step = "init"
            self._init(box_id)
            self._step = "run"
            self._run(box_id)
        except Exception as ex:
            self._failure_reason = "During {}\n{}\n{}".format(self._step, str(ex), traceback.format_exc())
            self._result = JobResult.FL
            with self._lock:
                self._cv.notify_all()
            
        if self._c_handler:
            if self._c_args:
                self._c_handler(*self._c_args)
            else:
                self._c_handler()

    def get_timeusage(self):
        self.wait()
        return self._timeusage

    def get_wallusage(self):
        self.wait()
        return self._wallusage

    def get_memusage(self):
        self.wait()
        return self._memusage
                
    def is_running(self):
        return self._step == "run"
    
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

    def exit_code(self):
        self.wait()
        return self._exitcode
    
    def failure_reason(self):
        self.wait()
        return self._failure_reason
                       
    def wait(self):
        if self._result != None:
            return
        
        with self._cv:
            while self._result == None:
                self._cv.wait()

    def get_object_path(self, *path):
        if not hasattr(self, "_box_id"):
            raise Exception("EPIC FAIL")
        return os.path.join(self._workdir, *path)
    
    def get_stdout_path(self):
        return os.path.join(self._workdir, "_files", "stdout")

    def get_stderr_path(self):
        return os.path.join(self._workdir, "_files", "stderr")
    
    def release(self):
        """
        Releases job and destroys all result
        """
        if hasattr(self, "_box_id"):
            self.wait()
            self._clean(self._box_id)
            self._judge._returnid(self._box_id)
            delattr(self, "_box_id")

    def __lt__(self, other):
        return self.__time < other.__time

class IsolatedJudge:
    def __init__(self):
        self._num_threads = 4
        
        self._queue = queue.PriorityQueue()
        self._boxes = queue.Queue()
        self._running = True
        
        for i in range(2 * self._num_threads):
            self._boxes.put(300 + i)

        self._threads = []
        for i in range(self._num_threads):
            thread = threading.Thread(target = IsolatedJudge._work, args = (self,))
            thread.start()
            self._threads.append(thread)
        
    def __enter__(self):
        return self

    def __exit__(self, *_):
        print("shutting down judging system")
        self._running = False
        for i in range(self._num_threads):
            self._queue.put((-1000, None))

        for thr in self._threads:
            thr.join()

        while not self._queue.empty():
            job = self._queue.get()[1]
            if job != None:
                job._just_fail()

    def _work(self):
        while True:
            job = self._queue.get()[1]
            if not self._running or job == None:
                return
            job._work(self._boxes.get())

    def _returnid(self, box_id):
        self._boxes.put(box_id)
    
    def new_job(self, env, limits, *command, in_file=None, c_handler=None, c_args=None, priority=50):
        """
        Creates new runnable Job 
        
        Keyword Arguments:
        env: use judge.new_env()
        limits: use judge.new_limits()
        in_file: path to the stdin.
        c_handler: completion handler to call, optional.
        c_args: args to path to completion handler

        priority: the priority of the taks, lower is more important, should be in range [0; 99].

        Other arguments:
        Specify the command to run in a standard way
        """

        job = IsolatedJob(self, env, limits, *command, in_file=in_file, c_handler=c_handler, c_args=c_args)
        self._queue.put((priority, job))
        return job
        
    def new_env(self):
        return IsolatedJobEnvironment()

    def new_limits(self):
        return SimpleJobLimits()

    def new_job_helper(self, target):
        if target == "compile.g++":
            import pmaker.jobhelper
            return pmaker.jobhelper.JobHelperCompilation(self)
        if target == "invoke.g++":
            import pmaker.jobhelper
            return pmaker.jobhelper.JobHelperInvokation(self)
        
        raise ValueError("Unsupported job helper type")

def new_judge():
    return IsolatedJudge()
