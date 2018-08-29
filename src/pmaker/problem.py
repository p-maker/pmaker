import os, os.path
import configparser
import json
import hashlib
import shutil

class ProblemError(RuntimeError):
    pass

class ProblemJobError(ProblemError):
    pass

class ProblemScriptInvalidError(ProblemError):
    pass

class ProblemJobOutdated(ProblemError):
    pass

class ProblemJobNotFoundError(ProblemError):
    pass

class ProblemNotUpdatedError(ProblemError):
    pass

class ProblemCompilationFail(ProblemError):
    def __init__(self, source, judge_result, exit_code, stderr):
        self.source       = source
        self.judge_result = judge_result
        self.exit_code    = exit_code
        self.stderr       = stderr

    def __str__(self):
        return "Compilation failed for {}\nJudge result: {}\nExit code: {}\nstderr:\n{}\n[END]\n".format(self.source, self.judge_result, self.exit_code, self.stderr)

def lookup_problem(base=os.path.realpath("."), doraise=False):
    while True:
        if os.path.isfile(os.path.join(base, "problem.cfg")):
            return new_problem(base)

        if os.path.dirname(base) == base:
            if doraise:
                raise ProblemError("Problem not found error")
            return None
        
        base = os.path.dirname(base)

def new_problem(homedir):
    return Problem(homedir)

class Test:
    def __init__(self, manual, cmd_parts=None, manual_path=None, group=None):
        self.cmd_parts   = cmd_parts
        self.manual      = manual
        self.manual_path = manual_path
        self.group       = group
        self.index       = None

    def is_manual(self):
        return self.manual

    def get_manual_path(self):
        return self.manual_path

    def get_cmd_parts(self):
        return self.cmd_parts
    
    def get_group(self):
        return self.group

    def has_group(self):
        return self.group != None

    def get_index(self):
        return self.index

    def _set_index(self, index):
        self.index = index

    def get_display_cmd(self):
        if self.is_manual():
            return ":manual {}".format(self.get_manual_path())
        return " | ".join(map(lambda x: " ".join(x), self.get_cmd_parts()))
    def export(self):
        """
        Returns object, acceptable for serializing with json

        Test index is not included in serialization
        """

        res = dict()
        res['manual'] = self.is_manual()
        if self.has_group():
            res['group'] = self.get_group()
            
        if self.is_manual():
            res['path'] = self.get_manual_path()
        else:
            res['cmd'] = self.get_cmd_parts()

        return res

    @staticmethod
    def load(data):
        if type(data) != dict:
            raise ValueError("Invalid data")

        def safe_get(field, cls, maybe_none=False):
            if maybe_none and field not in data:
                return None
            
            if field not in data or type(data[field]) != cls:
                raise ValueError("Invalid data")
            
            return data[field]
        
        manual = None
        group  = None
        mpath  = None
        mcmd   = None

        manual = safe_get("manual", bool)
        group  = safe_get("group", str, True)
        
        if manual:
            mpath = safe_get("path", str)
            if len(mpath) == 0:
                raise ValueError("Invalid data")
        else:
            mcmd = safe_get("cmd", list)
            for elem in mcmd:
                if type(elem) != list or len(elem) == 0:
                    raise ValueError("Invalid data")
                for val in elem:
                    if type(val) != str:
                        raise ValueError("Invalid data")

        return Test(manual, cmd_parts=mcmd, manual_path=mpath, group=group)

class ValidationStatus:
    def __init__(self, prob, data_file):
        self.prob = prob
        self.data_file = data_file

    def is_ok(self):
        with open(self.data_file, "r") as fp:
            return json.load(fp)["exit_code"] == 0
    
class TestSet:
    def __init__(self):
        self.tests = []

    def size(self):
        return len(self.tests)
    
    def add_test(self, test):
        if self.size() == 999:
            raise IndexError("It is not allowed to have more than 999 tests")
        
        self.tests.append(test)
        test._set_index(self.size())

    def by_index(self, index, noraise=False):
        if index <= 0 or index >= self.size() + 1:
            if noraise:
                return None
            raise IndexError("test index out of range")
        return self.tests[index - 1]

    def __len__(self):
        return len(self.tests)

    def __iter__(self):
        return self.tests.__iter__()

    def __getitem__(self, i):
        return self.by_index(i)
        
    def export(self):
        """
        Returns object, acceptable for serializing with json
        """

        res = list()
        for elem in self.tests:
            res.append(elem.export())

        return res

    @staticmethod
    def load(data):
        if type(data) != list:
            raise ValueError("Invalid data")

        testset = TestSet()
        testset.tests = list(map(Test.load, data))

        return testset

class ScriptInterpreter:
    def __init__(self, testset):
        self.testset = testset
        self.cur_group = None

    def load(self, script_lines):
        for line in script_lines:
            parts = line.strip().split()

            if len(parts) == 0:
                continue

            if parts[0][0] == "#":
                continue
            
            if parts[0] == ":manual":
                if len(parts) != 2:
                    raise ProblemScriptInvalidError("Failed to parse line \"{}\"".format(line))
                self.testset.add_test(Test(True, manual_path=parts[1], group=self.cur_group))
                continue

            if parts[0] == ":set_group":
                if len(parts) != 2:
                    raise ProblemScriptInvalidError("Failed to parse line \"{}\"".format(line))
                self.cur_group = parts[1]
                continue

            if parts[0] == ":unset_group":
                if len(parts) != 1:
                    raise ProblemScriptInvalidError("Failed to parse line \"{}\"".format(line))
                self.cur_group = None
                continue

            if parts[0].startswith(":"):
                raise ProblemScriptInvalidError("Failed to parse line \"{}\"".format(line))

            cmd = []
            cur_part = []
            for elem in parts:
                if elem == "|":
                    if len(cur_part) == 0:
                        raise ProblemScriptInvalidError()
                    cmd.append(cur_part)
                    cur_part = []
                else:
                    cur_part.append(elem)

            if len(cur_part) == 0:
                raise ProblemScriptInvalidError("Bad pipes at line \"{}\"".format(line))
            cmd.append(cur_part)
            self.testset.add_test(Test(False, cmd_parts = cmd, group=self.cur_group))
            
    def get_testset(self):
        return self.testset
        
class CacheableJob:    
    def run(self):
        """
        Should run the job
        
        In case of failure must raise exception (any)
        Otherwise, return an array of absolute paths (possibly outside the problem) this job deends.
        """
        raise NotImplementedError()

    @staticmethod
    def wrap(func):
        class CacheableJobImpl(CacheableJob):
            def run(self):
                return func()

        return CacheableJobImpl()
    
class JobProvider:
    def get_job(self, name):

        """
        Should either return a job, or None
        """
        return None

    @staticmethod
    def wrap(func):
        class JobProviderImpl(JobProvider):
            def get_job(self, name):
                return func(name)
        return JobProviderImpl()

    @staticmethod
    def wrap_simple(job_name, job_func):
        class JobProviderImpl(JobProvider):
            def get_job(self, name):
                if name == job_name:
                    return CacheableJob.wrap(job_func)
                else:
                    return None


def get_file_digest(path):
    m = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            data = fp.read(2048)
            if len(data) == 0:
                break
            m.update(data)
    return m.hexdigest()
                
class JobCache:
    def __init__(self, prob):
        self.prob = prob
        self.providers = []
        self.completed_jobs = set()
        self.digest_cache   = dict()

    def register_provider(self, provider):
        self.providers.append(provider)

    def file_digest(self, fl):
        if fl in self.digest_cache:
            return self.digest_cache[fl]

        digest = "_no_file_"
        if os.path.exists(fl):
            digest = get_file_digest(fl)
        
        self.digest_cache[fl] = digest
        return digest
            
    def run_job(self, job_id, check_only=False):
        if job_id in self.completed_jobs:
            return
        
        if self.prob.exists("work", "_jobs", job_id):
            jobinfo = None
            with open(self.prob.relative("work", "_jobs", job_id), "r") as fp:
                jobinfo = json.load(fp)

            if type(jobinfo) == list:
                ok = True
                for elem in jobinfo:
                    if type(elem) != list or len(elem) != 2 or self.file_digest(elem[0]) != elem[1]:
                        ok = False
                        break
                if ok:
                    return

        if check_only:
            raise ProblemJobOutdated()
        
        for prov in self.providers:
            job = prov.get_job(job_id)
            if job != None:
                lst = None
                try:
                    lst = job.run()
                except Exception as ex:
                    raise ProblemJobError()

                if type(lst) != list:
                    raise ProblemJobError()
                os.makedirs(self.prob.relative("work", "_jobs"), exist_ok=True)
                with open(self.prob.relative("work", "_jobs", job_id), "w") as fp:
                    json.dump(list(map(lambda x: (x, self.file_digest(x)), lst)), fp)

                self.completed_jobs.add(job_id)
                return
        raise ProblemJobNotFoundError()

    def safe_id_from_string(self, s):
        """
        Performs some modifications to string, such that:
        
        - Resulting string is a valid path entry
        - Doesn't contain any ".", "@" symbols
        - Such transformation is injective (collision-less)
        """

        def handle(ch):
            if ch == '_':
                return '__'
            if ch == '@':
                return '_a'
            if ch == '.':
                return '_b'
            return ch
        
        return "".join([handle(ch) for ch in s])

    def string_from_id(self, s):
        active = False

        lst = []
        for ch in s:
            if active:
                if ch == '_':
                    lst.append('_')
                elif ch == 'a':
                    lst.append('@')
                elif ch == 'b':
                    lst.append('.')
                else:
                    raise ValueError("Bad encoding")
                active = False
            else:
                if ch == '_':
                    active = True
                else:
                    lst.append(ch)
        if active:
            raise ValueError("Bad encoding")
        return "".join(lst)
                    
    def safe_id_from_slist(self, lst):
        """
        Generates some string from list, such that:
        
        - Resulting string is a valid path entry
        - Doesn't contain any "." symbols
        - Such transformation is injective (collision-less)
        """
        return "@".join(map(self.safe_id_from_string, lst))

    def slist_from_id(self, s):
        parts = s.split("@")
        return list(map(self.string_from_id, parts))


class ProblemBase:
    def __init__(self, homedir):
        self._homedir = homedir

    def relative(self, *args):
        """
        Convenience function for referrencing objects inside homedir
        """

        return os.path.join(self._homedir, *args)

    def exists(self, *args):
        """
        Convenience function for referrencing objects inside homedir
        """
        return os.path.exists(self.relative(*args))

    def parse_millis(self, s):
        pre,post = s.split('.', maxsplit=1)
        if len(post) > 3:
            raise ValueError("Bad millis specification")
        post = post + '0' * (3 - len(post))
        return 1000 * int(pre) + int(post)
    
class Problem(ProblemBase):
    def __init__(self, homedir, judge=None):
        super().__init__(homedir)

        parser = configparser.ConfigParser(delimiters=('=',), comment_prefixes=('#',))
        with open(self.relative("problem.cfg"), "r") as f:
            parser.readfp(f)

        self._judge          = judge
            
        self._model_solution = parser.get("main", "model_solution", fallback=None)
        self._time_limit     = self.parse_millis(parser.get("main", "time_limit"))
        self._mem_limit      = self.parse_millis(parser.get("main", "memory_limit"))
        self._validator      = None
        self._checker        = None
        self._script         = None
        
        if parser.get("main", "validator", fallback=None) != None:
            self._validator  = "source/" + parser.get("main", "validator")
        
        if parser.get("main", "checker", fallback=None) != None:
            self._checker  = "source/" + parser.get("main", "checker")

        if self._validator == None:
            for validator in ["validator.cpp", "validate.cpp"]:
                if self.exists(validator):
                    self._validator = validator
                    break
        
        if self._checker == None:
            for checker in ["checker.cpp", "check.cpp"]:
                if self.exists(checker):
                    self._checker = checker
                    break

        for script in ["script", "script.txt", "script.py", "script.sh"]:
            if self.exists(script):
                self._script = script
                break

        os.makedirs(self.relative("work"), exist_ok=True)
        self._job_cache = JobCache(self)
        self._tests = None

        self._job_cache.register_provider(JobProvider.wrap(self.__job_provider))
    
    def set_judge(self, judge):
        self._judge = judge

    def get_generator_limits(self):
        limits = self._judge.new_limits()
        limits.set_memorylimit(256 * 1000)
        limits.set_timelimit(5 * 1000)
        limits.set_timelimit_wall(10 * 1000)
        limits.set_proclimit(1)
        return limits

    def get_validation_limits(self):
        limits = self._judge.new_limits()
        limits.set_memorylimit(256 * 1000)
        limits.set_timelimit(5 * 1000)
        limits.set_timelimit_wall(10 * 1000)
        limits.set_proclimit(1)
        return limits

    def get_model_limits(self):
        limits = self._judge.new_limits()
        limits.set_memorylimit(256 * 1000)
        limits.set_timelimit(15 * 1000)
        limits.set_timelimit_wall(30 * 1000)
        limits.set_proclimit(1)
        return limits

    def get_problem_limits(self):
        limits = self._judge.new_limits()
        limits.set_memorylimit(self._mem_limit)
        limits.set_timelimit(self._time_limit)
        limits.set_timelimit_wall(2 * self._time_limit)
        limits.set_proclimit(1)
        return limits
    
    def get_test_input_data(self, test):
        if test.is_manual():
            return "mtest.{}".format(self._job_cache.safe_id_from_string(test.get_manual_path()))
        else:
            prev = ""
            for cmd_ in test.get_cmd_parts():
                cmd = list(cmd_) # copied
                if not self.exists("source", cmd[0]):
                    cmd[0] = cmd[0] + ".cpp"
                cur = "mgen.{}.{}".format(self._job_cache.safe_id_from_string(prev), self._job_cache.safe_id_from_slist(cmd))
                self._job_cache.run_job(cur)
                prev = cur
            return prev

    def get_test_output_data(self, test):
        return "ans." + self._job_cache.safe_id_from_string(self._model_solution) + "." + self._job_cache.safe_id_from_string(self.get_test_input_data(test))
    
    def get_validation(self, index):
        testset = self.get_testset(check_only=True)
        test = testset[index]
        
        group = test.get_group() if test.has_group() else ""
        path = self.get_test_input_data(test)

        return ValidationStatus(self, self.relative("work", "_data", "val.{}.{}".format(self._job_cache.safe_id_from_string(group), path)))
    
    def __job_provider(self, job):
        func = None
        if job == "tests":
            func = self.__do_gen_tests

        else:
            cmd, arg = job.split(".", maxsplit=1)
            
            if cmd == "mtest":
                func = lambda: self.__do_mpost(self._job_cache.string_from_id(arg))
            if cmd == "mgen":
                arg = arg.split(".", maxsplit=1)
                func = lambda: self.__do_mgen(self._job_cache.string_from_id(arg[0]), self._job_cache.slist_from_id(arg[1]))

            if cmd == "comp":
                func = lambda: self.__do_compile(self._job_cache.slist_from_id(arg))
            if cmd == "val":
                arg = arg.split(".", maxsplit=1)                
                func = lambda: self.__do_validate(self._job_cache.string_from_id(arg[0]), arg[1])
            if cmd == "ans":
                sol, tst = arg.split(".", maxsplit=1)
                sol = self._job_cache.string_from_id(sol)
                tst = self._job_cache.string_from_id(tst)

                if sol != self._model_solution:
                    raise ValueError("Unsupported solution")
                
                func = lambda: self.__do_gen_ans(tst, job)
        
        return CacheableJob.wrap(func)
    
    def __do_gen_tests(self):
        if not self._script:
            raise ProblemError("There is no script")
        
        lang = "bash"
        if self._script.endswith(".py"):
            lang = "python3"

        jh = self._judge.new_job_helper("invoke." + lang)
        limits = self._judge.new_limits()
        limits.set_memorylimit(16 * 1000)
        limits.set_timelimit(500) # half a second
        limits.set_proclimit(4)

        jh.set_limits(limits)
        jh.run(self.relative(self._script))
        jh.wait()

        if not jh.result().ok():
            jh.release()
            raise ProblemError("Failed to invoke script")
        
        interpreter = ScriptInterpreter(TestSet())
        interpreter.load(jh.read_stdout().split("\n"))
        jh.release()

        self._tests = interpreter.get_testset()
        with open(self.relative("work", "testset"), "w") as fp:
            json.dump(self._tests.export(), fp)

        return [self.relative(self._script)]

    def __do_compile(self, src, lang="g++"):
        if not os.path.isfile(self.relative(*src)):
            raise ProblemError("File {} doesn't exist".format("/".join(src)))
        jh = self._judge.new_job_helper("compile." + lang)
        limits = self._judge.new_limits()
        limits.set_memorylimit(256 * 1000)
        limits.set_timelimit(30 * 1000)
        limits.set_timelimit_wall(30 * 1000)
        limits.set_proclimit(4)

        jh.set_limits(limits)
        jh.run(self.relative(*src))
        jh.wait()

        if not jh.result().ok():
            err = ProblemCompilationFail(src, jh.result(), jh.exit_code(), jh.read_stderr())
            jh.release()
            raise err

        os.makedirs(self.relative("work", "compiled"), exist_ok=True)
        jh.fetch(self.compile_result(*src))
        jh.release()
        return [self.relative(*src)] # TODO
    
    def __do_mpost(self, testname):
        os.makedirs(self.relative("work", "_data"), exist_ok=True)
        with open(self.relative("tests.manual", testname), "r") as fsrc:
            with open(self.relative("work", "_data", "mtest." + testname), "w") as fdst:
                fdst.write(fsrc.read())

        return [self.relative("tests.manual", testname)]
    
    def __do_mgen(self, cmd_prev, cmd, lang="g++"):
        jh = self._judge.new_job_helper("invoke." + lang)
        jh.set_limits(self.get_generator_limits())

        in_file = None
        if cmd_prev != "":
            in_file = self.relative("work", "_data", cmd_prev)

        jh.run(self.compilation_result("source", cmd[0]), prog_args=cmd[1:], in_file=in_file)
        jh.wait()

        if not jh.result().ok():
            jh.release()
            raise ProblemError("Failed to run {}".format(cmd))

        os.makedirs(self.relative("work", "_data"), exist_ok=True)
        with open(self.relative("work", "_data", "mgen.{}.{}".format(self._job_cache.safe_id_from_string(cmd_prev), self._job_cache.safe_id_from_slist(cmd))), "w") as fp:
            fp.write(jh.read_stdout())

        jh.release()
        deps = [self.compilation_result("source", cmd[0])]
        if in_file != None:
            deps.append(in_file)
        return deps

    def __do_validate(self, group, test_path):
        jh = self._judge.new_job_helper("invoke.g++")
        jh.set_limits(self.get_validation_limits())

        in_file = self.relative("work", "_data", test_path)

        prog_args = []
        if group != "":
            prog_args = ["--group", group]
        jh.run(self.relative(self.compilation_result(self._validator)), prog_args=prog_args, in_file=in_file)
        jh.wait()
        
        if not jh.result().ok_or_re():
            raise ProblemError("Big validation failure for: {}".format(test_path))
        
        os.makedirs(self.relative("work", "_data"), exist_ok=True)
        safe_group = self._job_cache.safe_id_from_string(group)
        with open(self.relative("work", "_data", "val.{}.{}".format(safe_group, test_path)), "w") as fp:
            json.dump({"stdout": jh.read_stdout(), "stderr": jh.read_stderr(), "exit_code": jh.exit_code()}, fp)

        jh.release()
        deps = [self.relative(self.compilation_result(self._validator)), in_file]
        return deps

    def __do_gen_ans(self, test_path, out_path):
        jh = self._judge.new_job_helper("invoke.g++")
        jh.set_limits(self.get_model_limits())

        in_file = self.relative("work", "_data", test_path)

        jh.run(self.relative(self.compilation_result("solutions", self._model_solution)), in_file=in_file)
        jh.wait()
        
        if not jh.result().ok():
            reason = "Got: " + jh.result().name
            if jh.result().is_fail():
                reason += ", fail reason: " + jh.failure_reason()
            jh.release()
            raise ProblemError("Failed to generate answer for: {}, reason: {}".format(test_path, reason))
        
        os.makedirs(self.relative("work", "_data"), exist_ok=True)
        with open(self.relative("work", "_data", out_path), "w") as fp:
            fp.write(jh.read_stdout())

        jh.release()
        deps = [self.relative(self.compilation_result("solutions", self._model_solution)), in_file]
        return deps

    
    def get_testset(self, check_only=False):
        if self._tests != None:
            return self._tests

        self._job_cache.run_job("tests", check_only=check_only)
        if self._tests == None:
            with open(self.relative("work", "testset"), "r") as fp:
                self._tests = TestSet.load(json.load(fp))

        return self._tests

    def compile(self, *args, check_only=False):
        self._job_cache.run_job("comp.{}".format(self._job_cache.safe_id_from_slist(list(args)), check_only=check_only))

    def compilation_result(self, *args):
        return self.compile_result(*args)
    
    def compile_result(self, *args):
        return self.relative("work", "compiled", self._job_cache.safe_id_from_slist(list(args)))
        
    def update_tests(self, interactive=True):
        def iprint(*args, **kwargs):
            if interactive:
                print(*args, **kwargs)

        iprint("Running script")
        tests = self.get_testset()
        generators = []
        for test in tests:
            if not test.is_manual():
                for part in test.get_cmd_parts():
                    if not part[0] in generators:
                        generators.append(part[0])

        iprint("Compiling generators")
        for gen in generators:
            if not self.exists("source", gen):
                gen = gen + ".cpp"
            iprint("Compiling source/" + gen)
            self.compile("source", gen)
    
        iprint("Compiling checker")
        self.compile(self._checker)
        shutil.copyfile(self.compilation_result(self._checker), self.relative("work", "compiled", "check.cpp"))
        iprint("Generating tests")
        inputs = []
        
        for i in range(1, 1 + len(tests)):
            test = tests[i]
            
            if test.is_manual():
                self._job_cache.run_job("mtest.{}".format(self._job_cache.safe_id_from_string(test.get_manual_path())))
                inputs.append("mtest.{}".format(self._job_cache.safe_id_from_string(test.get_manual_path())))
            else:
                prev = ""
                for cmd_ in test.get_cmd_parts():
                    cmd = list(cmd_) # copied
                    if not self.exists("source", cmd[0]):
                        cmd[0] = cmd[0] + ".cpp"
                    cur = "mgen.{}.{}".format(self._job_cache.safe_id_from_string(prev), self._job_cache.safe_id_from_slist(cmd))
                    self._job_cache.run_job(cur)
                    prev = cur
                inputs.append(prev)
                
            iprint("Generating tests: {}/{}".format(i, len(tests)))

        iprint("Validating")
        if self._validator:
            self.compile(self._validator)
            
            for i in range(len(tests)):
                group = ""
                if tests[i + 1].has_group():
                    group = tests[i + 1].get_group()
                self._job_cache.run_job("val.{}.{}".format(self._job_cache.safe_id_from_string(group), inputs[i]))

                
            bad = []
            for i in range(len(tests)):
                if not self.get_validation(i + 1).is_ok():
                    bad.append(i + 1)

            if bad:
                more = True
                if len(bad) >= 10:
                    bad = bad[:10]
                iprint("[W] There are some validation problems, tests " + ",".join(map(str, bad)) + ("..." if more else ""))
                iprint("[W] Use test-view for more details")
        else:
            iprint("Validation skipped since there is no validator")


        iprint("Compiling jury solution")
        self.compile("solutions", self._model_solution)
        iprint("Generating jury answers")
        answers = []
        for i in range(len(tests)):
            self._job_cache.run_job("ans.{}.{}".format(self._job_cache.safe_id_from_string(self._model_solution), self._job_cache.safe_id_from_string(inputs[i])))
            answers.append("ans.{}.{}".format(self._job_cache.safe_id_from_string(self._model_solution), self._job_cache.safe_id_from_string(inputs[i])))

        iprint("Posting tests")
        if os.path.exists(self.relative("work", "tests")):
            shutil.rmtree(self.relative("work", "tests"))

        os.makedirs(self.relative("work", "tests"), exist_ok=True)
            
        for i in range(len(tests)):
            test_path = self.relative("work", "tests", "%.03d" % (i + 1))
            
            shutil.copyfile(self.relative("work", "_data", inputs[i]), test_path)
            shutil.copyfile(self.relative("work", "_data", answers[i]), test_path + ".a")

        iprint("Done!")

    def wipe(self, mrpropper=False):
        if mrpropper:
            shutil.rmtree(self.relative("work"))
        else:
            for part in ["compiled","_data", "_jobs", "tests", "testset"]:
                if os.path.isfile(self.relative("work", part)):
                    os.remove(self.relative("work", part))
                elif os.path.isdir(self.relative("work", part)):
                    shutil.rmtree(self.relative("work", part))

    def parse_exit_code(self, code):
        from pmaker.invocation import InvokationStatus

        db = {0: InvokationStatus.OK,
              1: InvokationStatus.WA,
              2: InvokationStatus.PE,
              3: InvokationStatus.CF,
              4: InvokationStatus.PE, # testlib calls it "dirt", we call it "pe".
        }

        if code in db:
            return db[code]
        return InvokationStatus.CF # assume it is check failed anyway.        
