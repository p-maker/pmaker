from pmaker.invocation import Invokation, InvokationStatus
import os
import json

class ArchivedInvokationDesc:
    def __init__(self, ainvocation, i, j):
        self.ainvocation = ainvocation
        self.the_i = i
        self.the_j = j

        self.info = ainvocation.info[self.the_i][self.the_j]
        if self.info == None:
            self.info = dict()
        
        self.tusage = self.info["time_usage"] if "time_usage" in self.info else None
        self.musage = self.info["mem_usage"] if "mem_usage" in self.info else None
        
    def is_final(self):
        return True

    def get_status(self):
        res = None
        if self.info != None and "result" in self.info:
            res = InvokationStatus[self.info["result"]]
        else:
            res = InvokationStatus.INCOMPLETE

        if self.tusage != None and self.tusage >= self.ainvocation.timelimit:
            res = res.make_tl(ignore_fail=True)
        return res

    def get_rusage(self):
        return (self.tusage, self.musage)

class ArchivedInvokation:
    def relative(self, *args):
        return os.path.join(self.workdir, *args)
    
    def __init__(self, workdir):
        self.workdir  = workdir
        self.metadata = None
        self.deep_fail = False

        self.timelimit = None
        
        try:
            with open(self.relative("meta.json")) as fp:
                self.metadata = json.load(fp)
                
            self.solutions    = self.metadata["solutions"]
            self.test_indices = self.metadata["test_indices"]
            self.timelimit    = self.metadata["timelimit"]
            self.memorylimit  = self.metadata["memorylimit"]
            
        except:
            self.deep_fail = True

        self.info = [[None for i in range(len(self.get_tests()))] for j in range(len(self.get_solutions()))]

        for i in range(len(self.get_solutions())):
            for j in range(len(self.get_tests())):
                try:
                    with open(self.relative("results", "{}_{}".format(i, j)), "r") as fp:
                        self.info[i][j] = json.load(fp)
                except:
                    pass

    def get_solutions(self):
        if self.deep_fail:
            return []

        return self.solutions

    def get_tests(self):
        if self.deep_fail:
            return []

        return self.test_indices

    def get_result(self, sol, tst):
        return self.get_descriptor(sol, tst).get_status()
    
    def get_descriptor(self, sol, tst):
        return ArchivedInvokationDesc(self, sol, tst)
        
        
class InvokationManager:
    def __init__(self, prob, homedir):
        self.prob    = prob
        self.homedir = homedir
        self.active  = dict()
        
    def list_invocations(self):
        lst = []

        print(self.homedir)
        if os.path.exists(self.homedir):
            for elem in os.listdir(self.homedir):
                try:
                    num = int(elem)
                    if 0 <= num and num <= 100000:
                        lst.append(num)
                except:
                    pass

        lst.sort()
        return lst

    def list_active(self):
        return self.active.keys()
    
    def new_invocation(self, judge, solutions, test_indices):
        timelim = self.prob.get_problem_limits().get_timelimit()
        memlim  = self.prob.get_problem_limits().get_memorylimit()
        lst = self.list_invocations()
        
        uid  = 0 if len(lst) == 0 else max(lst) + 1
        path = os.path.join(self.homedir, str(uid))
        
        os.makedirs(path)
        self.active[uid] = Invokation(judge, self.prob, solutions, test_indices, uid, path, timelim, memlim)

        return (uid, self.active[uid])

    def get_invocation(self, uid):
        if uid in self.active:
            return self.active[uid]
        elif uid in self.list_invocations():
            return ArchivedInvokation(os.path.join(self.homedir, str(uid)))
        else:
            return None

def new_invocation_manager(prob, homedir):
    return InvokationManager(prob, homedir)
