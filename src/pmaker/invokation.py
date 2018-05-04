from pmaker.enter import Problem
from enum import Enum
import uuid
import os, os.path

class InvokationStatus(Enum):
    WAITING   = -4
    COMPILING = -3
    CE        = -2
    CHECKING  = -1
    PENDING   =  0
    RUNNING   =  1
    OK        =  2
    RE        =  3
    WA        =  4
    PE        =  5
    ML        =  6
    TL        =  7
    TL_HARD   =  8
    WA_TL     =  9
    FL        =  10

class InvokeDesc:
    def __init__(self, prob, judge, limits, solution, test_no):
        self.prob     = prob
        self.judge    = judge
        self.limits   = limits
        self.solution = solution
        self.test_no  = test_no
        self.the_test = self.prob.get_test_by_index(self.test_no)
        self.state    = 0 # not started.
        
        self.totaltime = None
        self.totalmem  = None
        
    def start(self):
        jobhelper = self.judge.new_job_helper("invoke.g++")
        jobhelper.set_limits(self.limits)
        jobhelper.run(self.prob.relative("work", "compiled", "solutions", self.solution), in_file=self.the_test.get_path("input"), c_handler=self.invoke_done)

        self.jobhelper = jobhelper
        self.state = 1 # testing

    def invoke_done(self):
        rs = self.jobhelper.result()
        from pmaker.judge import JobResult
        
        self.totaltime = self.jobhelper.get_timeusage()
        self.totalmem  = self.jobhelper.get_memusage()
        
        if rs in [JobResult.TL, JobResult.TL_SOFT]:
            self.result = InvokationStatus.TL
            self.state = 3 # complete
            self.jobhelper.release()
            return
        
        if rs in [JobResult.RE]:
            self.result = InvokationStatus.RE
            self.state = 3 # complete
            self.jobhelper.release()
            return

        if rs in [JobResult.ML]:
            self.result = InvokationStatus.ML
            self.state = 3 # complete
            self.jobhelper.release()
            return

        if rs in [JobResult.FL]:
            self.result = InvokationStatus.FL
            print(self.jobhelper.get_failure_reason())
            self.state = 3 # complete
            self.jobhelper.release()
            return

        with open("/tmp/" + self.solution + "_" + str(self.test_no), "w") as fp:
            fp.write(self.jobhelper.read_stdout())
            self.jobhelper.release()

        jobhelper = self.judge.new_job_helper("invoke.g++")
        jobhelper.set_limits(self.limits)

        jobhelper.set_priority(30)
        jobhelper.add_file(self.the_test.get_path("input"), "/input")
        jobhelper.add_file(self.the_test.get_path("output"), "/correct")
        jobhelper.add_file("/tmp/" + self.solution + "_" + str(self.test_no), "/output")

        jobhelper.run(self.prob.relative("work", "compiled", "check.cpp"), prog_args=["input", "output", "correct"], c_handler=self.check_done)

        self.jobhelper = jobhelper
        self.state = 2 # checking
    def check_done(self):
        rs = self.jobhelper.result()
        from pmaker.judge import JobResult
        if not rs in [JobResult.OK, JobResult.RE]:
            self.result = InvokationStatus.FL
            print(self.jobhelper.get_failure_reason())
        else:
            if rs == JobResult.OK:
                self.result = InvokationStatus.OK
            else:
                self.result = InvokationStatus.WA
        self.state = 3
        self.jobhelper.release()
    
    def get_status(self):
        if self.state == 0:
            return InvokationStatus.PENDING
        if self.state == 1:
            if self.jobhelper.is_running():
                return InvokationStatus.RUNNING
            else:
                return InvokationStatus.PENDING
        if self.state == 2:
            return InvokationStatus.CHECKING
        return self.result
    
    def get_rusage(self):
        return (self.totaltime, self.totalmem)
    
class Invokation:
    def __init__(self, judge, prob, solutions, test_indices, uid, path):
        self.judge        = judge
        self.prob         = prob
        self.solutions    = solutions
        self.test_indices = test_indices
        
        self.compilation_jobs    = [None for i in range(len(solutions))]

        limits = self.judge.new_limits()
        limits.set_timelimit(1000 * self.prob.timelimit)
        limits.set_timelimit_hard(2 * 1000 * self.prob.timelimit)
        limits.set_timelimit_wall(4 * 1000 * self.prob.timelimit)
        limits.set_memorylimit(256 * 1000)
        
        self.descriptors        = [[InvokeDesc(prob, judge, limits, solutions[i], test_indices[j]) for j in range(len(test_indices))] for i in range(len(solutions))]
        
    def start(self):
        for i in range(len(self.solutions)):
            limits = self.judge.new_limits()
            limits.set_timelimit(30 * 1000)
            limits.set_timelimit_wall(45 * 1000)
            limits.set_memorylimit(256 * 1000)
            limits.set_proclimit(4)
            
            job_this = self.judge.new_job_helper("compile.g++")
            job_this.set_limits(limits)
            job_this.run(self.prob.relative("solutions", self.solutions[i]))
            self.compilation_jobs[i] = job_this

        for i in range(len(self.solutions)):
            self.compilation_jobs[i].wait()
            if self.compilation_jobs[i].is_ok():
                self.compilation_jobs[i].fetch(self.prob.relative("work", "compiled", "solutions", self.solutions[i]))
            self.compilation_jobs[i].release()

        # TODO: fetch compilation log.

        for j in range(len(self.test_indices)):
            for i in range(len(self.solutions)):
                if self.compilation_jobs[i].is_ok():
                    self.descriptors[i][j].start()

    def get_solutions(self):
        return self.solutions

    def get_tests(self):
        return self.test_indices
            
    def get_result(self, solution_index, test_index):
        if self.compilation_jobs[solution_index].is_ready():
            if self.compilation_jobs[solution_index].is_ok():
                return self.descriptors[solution_index][test_index].get_status()
            else:
                return InvokationStatus.CE
        elif self.compilation_jobs[solution_index].is_running():
            return InvokationStatus.COMPILING
        else:
            return InvokationStatus.WAITING

def new_invokation(judge, prob, solutions, test_indices):
    uid = str(uuid.uuid4())
    path = prob.relative("work", "invokations", uid)
    return Invokation(judge, prob, solutions, test_indices, uid, path)

