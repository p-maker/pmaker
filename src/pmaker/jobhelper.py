import shutil

class JobHelperCommon:
    def __init__(self, judge):
        self.judge  = judge
        self.limits = None
        self.env    = self.judge.new_env()
        self.priority = 50
        
    def add_file(self, host, virtual):
        self.env.add_file(host, virtual)

    def set_priority(self, priority):
        self.priority = priority
        
    def set_limits(self, limits):
        self.limits = limits

    def is_ready(self):
        return self.job.is_ready()

    def is_running(self):
        return self.job.is_running()

    def get_timeusage(self):
        return self.job.get_timeusage()

    def get_wallusage(self):
        return self.job.get_wallusage()
    
    def get_memusage(self):
        return self.job.get_memusage()
    
    def wait(self):
        self.job.wait()
    
    def is_ok(self):
        return self.result().ok()

    def is_ok_or_re(self):
        return self.result().ok_or_re()
    
    def result(self):
        return self.job.result()

    def exit_code(self):
        return self.job.exit_code()
    
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
            self.job.release()

    def __enter__(self):
        return self

    def __exit__(self, _1, _2, _3):
        self.release()

class JobHelperCompilation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, lang=None, c_handler=None, c_args=None):
        env = self.env
        env.add_file(source, "/source.cpp")

        self.job = self.judge.new_job(env, self.limits, "/usr/bin/g++", "-Wall", "-Wextra", "-std=c++14", "-O2", "/box/source.cpp", "-o", "/box/source", c_handler=c_handler, c_args=c_args, priority=self.priority)

    def fetch(self, result):
        shutil.copyfile(self.job.get_object_path("source"), result)


        
class JobHelperInvokation(JobHelperCommon):
    def __init__(self, judge):
        super().__init__(judge)

    def run(self, source, in_file=None, prog_args=None, c_handler=None, c_args=None):
        env = self.env
        env.add_exe_file(source, "/prog")
        if prog_args == None:
            prog_args = []
        self.job = self.judge.new_job(env, self.limits, *(["./prog"] + prog_args), in_file=in_file, c_handler=c_handler, c_args=c_args, priority=self.priority)


        
