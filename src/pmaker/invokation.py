from pmaker.enter import Problem
from enum import IntEnum
import json
import os, os.path

class InvokationStatus(IntEnum):
    INCOMPLETE = -9
    WAITING    = -8
    COMPILING  = -7
    CE         = -6
    CHECKING   = -5
    PENDING    = -4
    RUNNING    = -3
    CF         = -2 # ignore other details, checker has failed.
    FL         = -1 # different from CF, CF is for checker fail, FL is for system fail.
    
    OK        =  0
    RE        =  1
    WA        =  2
    PE        =  3
    ML        =  4

    TL_OK     =  5
    TL_RE     =  6
    TL_WA     =  7
    TL_PE     =  8
    TL_ML     =  9  # well, whatever.
    
    TL        =  10 # TL (HARD edition)

    def make_tl(self, ignore_fail=False):
        if InvokationStatus.OK <= self <= InvokationStatus.ML:
            return InvokationStatus(self.value + 5)

        if ignore_fail:
            return self
        raise ValueError("Can't add TL to the verdict")

    def is_tl(self):
        return InvokationStatus.TL_OK <= self <= InvokationStatus.TL
    
    def undo_tl(self, ignore_fail=False):
        if InvokationStatus.TL_OK <= self <= InvokationStatus.TL_ML:
            return InvokationStatus(self.value - 5)
        if self.value == InvokationStatus.TL:
            return self
        if ignore_fail:
            return self

        raise ValueError("Can't remove TL from verdict")


class InvokeDesc:
    def __init__(self, invokation, limits, solution, test_no, export):
        self.invokation = invokation
        self.prob       = invokation.prob
        self.judge      = invokation.judge
        self.limits     = limits
        self.solution   = solution
        self.test_no    = test_no
        self.export     = export
        self.the_test   = self.prob.get_test_by_index(self.test_no)
        self.state      = 0 # not started.
        
        self.totaltime = None
        self.totalmem  = None

    def redump(self):
        try:
            with open(self.invokation.relative("results", self.export), "w") as fp:
                db = {}
                if self.totaltime:
                    db["time_usage"] = self.totaltime
                if self.totalmem:
                    db["mem_usage"] = self.totalmem
                if self.state == 3:
                    db["result"]    = self.result.name
                json.dump(db, fp)
        except:
            pass
            
    def start(self, is_ce=False):
        if is_ce:
            self.result = InvokationStatus.CE
            self.state = 3
            self.redump()
            return
        
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

        with open(self.invokation.relative("output", self.export), "w") as fp:
            fp.write(self.jobhelper.read_stdout())
        with open(self.invokation.relative("output", self.export + "_err"), "w") as fp:
            fp.write(self.jobhelper.read_stderr())
        if self.jobhelper.is_ok_or_re():
            with open(self.invokation.relative("output", self.export + "_code"), "w") as fp:
                fp.write(str(self.jobhelper.exit_code()))
        
        if rs in [JobResult.TL]:
            self.result = InvokationStatus.TL
            self.state = 3 # complete
            self.jobhelper.release()
            self.redump()
            return
        
        if rs in [JobResult.RE, JobResult.SG]:
            self.result = InvokationStatus.RE
            self.state = 3 # complete
            self.jobhelper.release()
            self.redump()
            return

        if rs in [JobResult.ML]:
            self.result = InvokationStatus.ML
            self.state = 3 # complete
            self.jobhelper.release()
            self.redump()            
            return

        if rs in [JobResult.FL]:
            self.result = InvokationStatus.FL
            print(self.jobhelper.get_failure_reason())
            self.state = 3 # complete
            self.jobhelper.release()
            self.redump()
            return
                        
        self.jobhelper.release()

        jobhelper = self.judge.new_job_helper("invoke.g++")
        jobhelper.set_limits(self.limits)

        jobhelper.set_priority(30)
        jobhelper.add_file(self.the_test.get_path("input"), "/input")
        jobhelper.add_file(self.the_test.get_path("output"), "/correct")
        jobhelper.add_file(self.invokation.relative("output", self.export), "/output")

        jobhelper.run(self.prob.relative("work", "compiled", "check.cpp"), prog_args=["input", "output", "correct"], c_handler=self.check_done)

        self.jobhelper = jobhelper
        self.state = 2 # checking
        self.redump()
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
                code = self.jobhelper.exit_code()
                self.result = self.prob.parse_exit_code(code)

        try:
            with open(self.invokation.relative("output", self.export + "_check"), "w") as fp:
                fp.write(self.jobhelper.read_stderr())
        except:
            raise
        if rs.ok_or_re():
            try:
                with open(self.invokation.relative("output", self.export + "_checkcode"), "w") as fp:
                    fp.write(str(self.jobhelper.exit_code()))
            except:
                pass
        
                
        self.state = 3
        self.redump()
        self.jobhelper.release()

    def is_final(self):
        return self.state == 3
        
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
        
        if self.totaltime >= self.invokation.timelimit:
            return self.result.make_tl(ignore_fail=True)
        else:
            return self.result
    
    def get_rusage(self):
        return (self.totaltime, self.totalmem)
    
class Invokation:
    def relative(self, *args):
        return os.path.join(self.workdir, *args)
    
    def __init__(self, judge, prob, solutions, test_indices, uid, path, TL, ML):
        self.judge        = judge
        self.prob         = prob
        self.solutions    = solutions
        self.test_indices = test_indices

        self.workdir = path

        with open(self.relative("meta.json"), "w") as fp:
            json.dump({"solutions": self.solutions,
                       "test_indices": self.test_indices,
                       "timelimit": TL,
                       "memorylimit": ML},
                      fp)

        os.makedirs(self.relative("results"))
        os.makedirs(self.relative("output"))
        os.makedirs(self.relative("compilations"))
        
        self.timelimit   = TL
        self.memorylimit = ML
        
        self.compilation_jobs    = [None for i in range(len(solutions))]

        limits = self.judge.new_limits()
        limits.set_timelimit(2 * TL)
        limits.set_timelimit_wall(3 * TL)
        limits.set_memorylimit(ML)
        
        self.descriptors        = [[InvokeDesc(self, limits, solutions[i], test_indices[j], export="{}_{}".format(i, j)) for j in range(len(test_indices))] for i in range(len(solutions))]
        
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
            if self.compilation_jobs[i].is_ok_or_re():
                with open(self.relative("compilations", "{}_out".format(i)), "w") as fp:
                    fp.write(self.compilation_jobs[i].read_stdout())
                with open(self.relative("compilations", "{}_err".format(i)), "w") as fp:
                    fp.write(self.compilation_jobs[i].read_stderr())
                with open(self.relative("compilations", "{}_code".format(i)), "w") as fp:
                    fp.write(str(self.compilation_jobs[i].exit_code()))
            
            if self.compilation_jobs[i].is_ok():
                self.compilation_jobs[i].fetch(self.prob.relative("work", "compiled", "solutions", self.solutions[i]))
            self.compilation_jobs[i].release()

        for j in range(len(self.test_indices)):
            for i in range(len(self.solutions)):
                is_ce = not self.compilation_jobs[i].is_ok()
                self.descriptors[i][j].start(is_ce = is_ce)
                    
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

    def get_descriptor(self, sol, tst):
        return self.descriptors[sol][tst]
