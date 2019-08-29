import shutil, stat, os

from pmaker.judge import JobResult 

class JobHelperCommon:
    def __init__(self, judge):
        self.judge  = judge
        self.limits = None
        self.env    = self.judge.new_env()
        self.priority = 50
        self.job = None

        # store this even after the inner job was released
        self._result = None
        self._exit_code = None
        self._userdesc = None

    def set_userdesc(self, val):
        self._userdesc = val
        
    def add_file(self, host, virtual):
        self.env.add_file(host, virtual)

    def set_priority(self, priority):
        self.priority = priority
        
    def set_limits(self, limits):
        self.limits = limits

    def is_ready(self):
        if self._result:
            return True # job finished => "Ready"
        return self.job.is_ready()

    def is_running(self):
        if not self.job:
            return False
        return self.job.is_running()

    def get_timeusage(self):
        return self.job.get_timeusage()

    def get_wallusage(self):
        return self.job.get_wallusage()
    
    def get_memusage(self):
        return self.job.get_memusage()
    
    def wait(self):
        if self.job:
            self.job.wait()
    
    def is_ok(self):
        return self.result().ok()

    def is_ok_or_re(self):
        return self.result().ok_or_re()
    
    def result(self):
        if self._result:
            return self._result
        return self.job.result()

    def exit_code(self):
        if self._exit_code:
            return self._exit_code
        return self.job.exit_code()

    def failure_reason(self):
        return self.job.failure_reason()
    
    def get_failure_reason(self):
        return self.job.failure_reason()
    
    def read_stdout(self):
        with open(self.job.get_stdout_path(), "r") as f:
            return f.read()

    def read_stderr(self):
        with open(self.job.get_stderr_path(), "r") as f:
            return f.read()
        
    def release(self):
        if self.job:
            self._result = self.job.result()
            self._exit_code = self.job.exit_code()
            
            self.job.release()
            self.job = None

    def __enter__(self):
        return self

    def __exit__(self, _1, _2, _3):
        self.release()

class JobHelperDumb(JobHelperCommon):
    def __init__(self, judge):
        self.job = None
        super().__init__(judge)
    
    def is_ready(self):
        return True

    def is_running(self):
        return False

    def get_timeusage(self):
        return 0

    def get_wallusage(self):
        return 0
    
    def get_memusage(self):
        return 0
    
    def wait(self):
        pass
    
    def result(self):
        return JobResult.OK

    def exit_code(self):
        return 0

    def get_failure_reason(self):
        return ""
    
    def read_stdout(self):
        return ""

    def read_stderr(self):
        return ""
        
class JobHelperCompilation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, lang=None, c_handler=None, c_args=None):
        env = self.env
        env.add_file(source, "/source.cpp")

        self.job = self.judge.new_job(env, self.limits, "/usr/bin/g++", "-Wall", "-Wextra", "-std=c++14", "-O2", "/box/source.cpp", "-o", "/box/source", c_handler=c_handler, c_args=c_args, priority=self.priority, userdesc=self._userdesc)

    def fetch(self, result, runnable=False):
        shutil.copyfile(self.job.get_object_path("source"), result)
        if runnable:
            os.chmod(result, stat.S_IRWXU | stat.S_IROTH | stat.S_IRGRP)

class JobHelperPyCompilation(JobHelperDumb):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, c_handler=None, c_args=None):
        self.__source = source

        if c_args == None:
            c_args = []
            
        if c_handler:
            c_handler(*c_args)

    def fetch(self, result, runnable=False):
        with open(result, "w") as fp:
            # disable site package import
            # cause failure in the sandbox
            fp.write("#!/usr/bin/python3 -S\n")
            with open(self.__source) as src:
                fp.write(src.read())
        
        if runnable:
            os.chmod(result, stat.S_IRWXU | stat.S_IROTH | stat.S_IRGRP)

class JobHelperInvokation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, in_file=None, prog_args=[], c_handler=None, c_args=None):
        env = self.env
        env.add_exe_file(source, "/prog")
        self.job = self.judge.new_job(env, self.limits, *(["./prog"] + prog_args), in_file=in_file, c_handler=c_handler, c_args=c_args, priority=self.priority, userdesc=self._userdesc)

#Note: unused
class JobHelperPyInvokation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, in_file=None, prog_args=[], c_handler=None, c_args=None):
        env = self.env
        env.add_file(source, "/prog.py")
        
        self.job = self.judge.new_job(env, self.limits, *(["/usr/bin/python3", "./prog.py"] + prog_args), in_file=in_file, c_handler=c_handler, c_args=c_args, priority=self.priority)

#Note: unused
class JobHelperBashInvokation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, in_file=None, prog_args=[], c_handler=None, c_args=None):
        env = self.env
        env.add_file(source, "/prog.sh")
        
        self.job = self.judge.new_job(env, self.limits, *(["/bin/bash", "./prog.sh"] + prog_args), in_file=in_file, c_handler=c_handler, c_args=c_args, priority=self.priority)

