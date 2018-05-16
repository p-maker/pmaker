import sys, os, os.path, configparser, subprocess, shutil, tempfile, time

def error(msg):
    print(msg)
    sys.exit(1)

class NotUpdatedError(Exception):
    pass
    
class Test:
    def __init__(self, manual, path=None, cmd=None, group=""):
        self.manual = manual

        if manual:
            self.path = path
        else:
            self.cmd = cmd
        
        self.group = group

    def is_manual(self):
        return self.manual

    def get_path(self):
        return self.path

    def get_display_cmd(self):
        if self.is_manual():
            return ":manual {}".format(self.get_path())
        else:
            return self.get_cmd()
    
    def get_cmd(self):
        return self.cmd

    def get_group(self):
        return self.group

    def has_group(self):
        return self.get_group() != None

class IndexedTest:
    def __init__(self, prob, test, index):
        self._prob = prob
        self._test = test
        self._index = index
        
        if type(self._index) is not int or self._index <= 0 or self._index >= 1000:
            raise ValueError("Bad test index")

    def test(self):
        return self._test
    
    def index(self):
        return self._index

    def prob(self):
        return self._prob
    
    def index_str(self):
        return "%03d" % self.index()

    def get_group(self):
        return self.test().get_group()

    def has_group(self):
        return self.test().has_group()
    
    def get_path(self, obj):
        """
        Get path to the test

        Keyword arguments:
        obj --- Either "input" or "output"
        """

        if obj not in ["input", "output"]:
            raise ValueError()
        
        suffix = "" if obj == "input" else ".a"
        
        return self.prob().relative("work", "tests", self.index_str() + suffix)
        
    def get_display_cmd(self):
        return self.test().get_display_cmd()

class Problem:
    def relative(self, *args):
        return os.path.join(self.home, *args)
    
    def __init__(self, home):
        self.home = home
        
        parser = configparser.ConfigParser(delimiters=('=',), comment_prefixes=('#',))
        with open(self.relative("problem.cfg"), "r") as f:
            parser.readfp(f)

        self.source_dir    = parser.get("files", "source_dir", fallback="source")
        self.solutions_dir = parser.get("files", "solutions_dir", fallback="solutions")
        
        self.validator  = parser.get("files", "validator",  fallback=None)        
        self.checker    = parser.get("files", "checker",    fallback=None)
        self.script     = parser.get("files", "script",     fallback=None)

        self.model      = parser.get("main", "model_solution", fallback=None)
        self.timelimit  = parser.getfloat("main", "time_limit",    fallback=None)
        self.memlimit  = parser.getfloat("main", "memory_limit",    fallback=None)
        
        if not self.validator:
            for validator in ["validator.cpp", "validate.cpp"]:
                if os.path.exists(validator):
                    self.validator = validator
                if os.path.exists(os.path.join(self.source_dir, validator)):
                    self.validator = os.path.join(self.source_dir, validator)
        
        if not self.checker:
            for checker in ["checker.cpp", "check.cpp"]:
                if os.path.exists(os.path.join(checker)):
                    self.checker = checker

        if not self.script:
            for script in ["script", "script.sh", "script.py"]:
                if os.path.exists(script):
                    self.script = script

        self.compile_cache = dict()
        self.tests = None
        os.makedirs("work", exist_ok=True)
        
    def call_cmd(self, cmd, cwd=None, text=True, nocache=False, input_data=None):
        print("running: {}".format(cmd), " +input" if input_data else "")
        
        if cwd == None:
            cwd = self.home

        if input_data:
            with tempfile.NamedTemporaryFile(prefix="infile_", dir=os.path.join("work", "temp"), mode="w+") as tmp:
                tmp.write(input_data)
                tmp.seek(0)
                return subprocess.check_output(cmd, cwd=cwd, universal_newlines=text, stdin=tmp.file)
        else:
            return subprocess.check_output(cmd, cwd=cwd, universal_newlines=text)

    def compile(self, fl):
        if fl in self.compile_cache:
            return self.compile_cache[fl]
        else:
            os.makedirs(os.path.dirname(os.path.join("work", "compiled", fl)), exist_ok=True)
            self.call_cmd(["g++", "-Wall", "-Wextra", "-std=c++14", "-O2", fl, "-o", os.path.join("work", "compiled", fl)])
            self.compile_cache[fl] = os.path.join("work", "compiled", fl)

            return os.path.join("work", "compiled", fl)
    
    def get_test_list(self):
        if not self.script:
            raise RuntimeError("script is not available")

        if self.tests != None:
            return self.tests

        txt = self.call_cmd("./{}".format(self.script))
        self.tests = []

        cur_group = None
        for line in txt.split("\n"):
            line = line.strip()
            if line == "" or line.startswith("#"):
                continue
            
            if line.startswith(":"):
                if line.startswith(":set_group "):
                    cur_group = line[len(":set_group "):]
                elif line == ":unset_group":
                    cur_group = None
                elif line.startswith(":manual "):
                    self.tests.append(Test(manual=True, path=line[len(":manual "):], group=cur_group))
                else:
                    raise RuntimeError("Invalid command in script file: {}".format(line))
            else:
                self.tests.append(Test(manual=False, cmd=line, group=cur_group))

        return self.tests

    def get_test_by_index(self, index):
        """
        Returns test or None
        
        Keyword arguments:
        index: test index as int
        """

        test_list = self.get_tests(noupdate=True)
        if 1 <= index <= len(test_list):
            return IndexedTest(self, test_list[index - 1], index)
        return None
    
    def get_tests(self, noupdate=False):
        lst = self.get_test_list()
        return [IndexedTest(self, lst[i], i + 1) for i in range(len(lst))]

    def parse_exit_code(self, code):
        from pmaker.invokation import InvokationStatus

        db = {0: InvokationStatus.OK,
              1: InvokationStatus.WA,
              2: InvokationStatus.PE,
              3: InvokationStatus.CF,
              4: InvokationStatus.PE, # testlib calls it "dirt", we call it "pe".
        }

        if code in db:
            return db[code]
        return InvokationStatus.CF # assume it is check failed anyway.        
    
    def gen_tests(self):
        print("generating tests")
        
        if self.checker:
            self.compile(self.checker)
        
        tests = self.get_test_list()
        if len(tests) >= 1000:
            raise RuntimeError("too much tests")

        if os.path.exists(os.path.join("work", "tests")):
            shutil.rmtree(os.path.join("work", "tests"))
        for (test, index) in zip(tests, range(1, 1001)):
            output = None
            if test.is_manual():
                with open(os.path.join("tests.manual", test.get_path()), "r") as f:
                    output = f.read()
            else:
                for part in test.get_cmd().split("|"):
                    sub = part.split()
                    if len(sub) == 0:
                        raise RuntimeError("invalid command")

                    gen_name = sub[0]
                    if not gen_name.endswith(".cpp"):
                        gen_name = gen_name + ".cpp"
    
                    generator = self.compile(os.path.join("source",gen_name))
                    output = self.call_cmd([generator] + sub[1:], input_data=output)
                
            os.makedirs(os.path.join("work", "tests"), exist_ok=True)
            with open(os.path.join("work", "tests", "%03d" % index), "w") as f:
                f.write(output)

        if self.model:
            self.compile(os.path.join(self.solutions_dir, self.model))
            for (_, index) in zip(tests, range(1, 1001)):
                with open(os.path.join("work", "tests", "%03d" % index), "rb") as inp:
                    with open(os.path.join("work", "tests", "%03d.a" % index), "wb") as out:
                        subprocess.check_call([os.path.join("work", "compiled", "solutions", self.model)], stdin=inp, stdout=out)

        if not self.validator:
            print("Validation skipped since there is no validator")
        else:
            self.compile(self.validator)
            print("validating tests...")
            for (test, index) in zip(tests, range(1, 1001)):
                group_info = ["--group", test.get_group()] if test.get_group() else []

                with open(os.path.join("work", "tests", "%03d" % index)) as test_file:
                    responce = subprocess.run([os.path.join("work", "compiled", self.validator)] + group_info, stdin=test_file, stdout=subprocess.PIPE, universal_newlines=True)

                if responce.returncode != 0:
                    print("test %-3d: FAIL, validator returned %d code" % index % responce.returncode)
                    raise RuntimeError("Failed to validate tests")            
                else:
                    print("test %-3d: OK" % index)
    
    def compile_new(self, fl, judge):
        if fl in self.compile_cache:
            return self.compile_cache[fl]
        else:
            os.makedirs(os.path.dirname(os.path.join("work", "compiled", fl)), exist_ok=True)
            
            limits = judge.new_limits()
            limits.set_proclimit(4)
            limits.set_timelimit(30 * 1000)
            limits.set_timelimit_wall(45 * 1000)
            limits.set_memorylimit(256 * 1000)
            
            with judge.new_job_helper("compile.g++") as jh:
                jh.set_limits(limits)

                jh.run(fl)
                jh.wait()

                print(jh.job.result())
                if not jh.is_ok():
                    print("FAIL: ", jh.get_failure_reason())

                    print("")
                    print("[stdout]")
                    print(jh.read_stdout())
                    print("[stderr]")
                    print(jh.read_stderr())
                    
                    raise RuntimeError("CE")
                jh.fetch(os.path.join("work", "compiled", fl))

            self.compile_cache[fl] = os.path.join("work", "compiled", fl)
            return os.path.join("work", "compiled", fl)

                    
    def gen_tests_new(self, judge):
        print("generating tests [beta]")
        
        if self.checker:
            self.compile_new(self.checker, judge)
        
        tests = self.get_test_list()
        if len(tests) >= 1000:
            raise RuntimeError("too much tests")

        if os.path.exists(os.path.join("work", "tests")):
            shutil.rmtree(os.path.join("work", "tests"))
        for (test, index) in zip(tests, range(1, 1000)):
            output = None
            if test.is_manual():
                with open(os.path.join("tests.manual", test.get_path()), "r") as f:
                    output = f.read()
            else:
                for part in test.get_cmd().split("|"):
                    sub = part.split()
                    if len(sub) == 0:
                        raise RuntimeError("invalid command")

                    gen_name = sub[0]
                    if not gen_name.endswith(".cpp"):
                        gen_name = gen_name + ".cpp"
    
                    generator = self.compile_new(os.path.join("source",gen_name), judge)
                    output = self.call_cmd([generator] + sub[1:], input_data=output)
                
            os.makedirs(os.path.join("work", "tests"), exist_ok=True)
            with open(os.path.join("work", "tests", "%03d" % index), "w") as f:
                f.write(output)

        if self.model:
            self.compile(os.path.join(self.solutions_dir, self.model))
            for (_, index) in zip(tests, range(1, 1001)):
                with open(os.path.join("work", "tests", "%03d" % index), "rb") as inp:
                    with open(os.path.join("work", "tests", "%03d.a" % index), "wb") as out:
                        subprocess.check_call([os.path.join("work", "compiled", "solutions", self.model)], stdin=inp, stdout=out)

        if not self.validator:
            print("Validation skipped since there is no validator")
        else:
            self.compile_new(self.validator, judge)
            print("validating tests...")
            for (test, index) in zip(tests, range(1, 1001)):
                group_info = ["--group", test.get_group()] if test.get_group() else []

                with open(os.path.join("work", "tests", "%03d" % index)) as test_file:
                    responce = subprocess.run([os.path.join("work", "compiled", self.validator)] + group_info, stdin=test_file, stdout=subprocess.PIPE, universal_newlines=True)

                if responce.returncode != 0:
                    print("test %-3d: FAIL, validator returned %d code" % index % responce.returncode)
                    raise RuntimeError("Failed to validate tests")            
                else:
                    print("test %-3d: OK" % index)

                    
                    
def lookup_problem(base):
    while True:
        if os.path.isfile(os.path.join(base, "problem.cfg")):
            return Problem(base)

        if os.path.dirname(base) == base:
            return None
        
        base = os.path.dirname(base)

help_info = []
commands_list = []

def cmd(want=[], arg=None, manual=None, long_help=None):
    def wrapper(f):
        def new_func(argv, __ptr=0, __kwargs=dict()):
            if (__ptr == len(want)):
                return f(**__kwargs)

            feature = want[__ptr]
            if feature == "prob-old":
                prob = lookup_problem(os.path.realpath("."))
                if not prob:
                    error("fatal: couldn't find problem")
                    return 1

                __kwargs["prob"] = prob
                return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)
            
            if feature == "prob":
                import pmaker.problem
                prob = pmaker.problem.lookup_problem()
                if not prob:
                    error("fatal: couldn't find problem")
                    return 1

                __kwargs["prob"] = prob
                return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)

            if feature == "imanager":
                from pmaker.invokation_manager import new_invokation_manager
                
                __kwargs["imanager"] = new_invokation_manager(__kwargs["prob"], __kwargs["prob"].relative("work", "invokations"))
                return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)

            if feature == "ui":
                from pmaker.ui.web.web import WebUI
                __kwargs["ui"] = WebUI(__kwargs["prob"])
                return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)

            if feature == "argv":
                __kwargs["argv"] = argv
                return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)
            
            if feature == "judge":
                from pmaker.judge import new_judge
                with new_judge() as judge:
                    __kwargs["judge"] = judge
                    return new_func(argv, __ptr=__ptr+1, __kwargs=__kwargs)

            raise ValueError("Unsupported feature {}".format(feature))

        if (manual):
            help_info.append((arg, manual, long_help))
        commands_list.append((arg, new_func))
        return new_func

    return wrapper

@cmd(want=["prob", "judge"], arg="tests", manual="Update problem's tests, solutions, etc.",
     long_help = """tests command, does the following:
     
   * Compiles the checker.
   * Runs and analyses test script
   * Compiles required generators
   * Generates all tests
   * Compiles validator and validates tests (if validator present)
   * Compiles model solution
   * Generates all model answers

Due to heavy usage of cache, many jobs will be skipped, if they are up to date.
     """)
def cmd_tests(prob=None, judge=None):
    prob.set_judge(judge)
    prob.update_tests()
    return 0

@cmd(want=["prob-old"], arg="tests-old")
def cmd_tests(prob=None):
    prob.gen_tests()
    return 0

@cmd(want=["prob-old", "imanager", "ui"], arg="invokation-list",
     manual="Show previous invokations",
     long_help="""Starts the web server so you can examine previous invokations
     
See http://localhost:8128/invokation for invokation list
And http://localhost:8128/invokation/<invokation_no> for the previous invokation
     """)
def cmd_invokation_list(prob=None, imanager=None, ui=None):
    ui.mode_invokation_list(imanager)
    ui.start()
    return 0

@cmd(want=["prob-old", "imanager", "judge", "ui", "argv"], arg="invoke",
     manual="Invoke specified solutions",
     long_help="""Invokes the specified solutions

Usage: pmaker invoke [list-of-solutions],
or     pmaker invoke @all

You will probably want to run "pmaker tests" prior this command.

The link http://localhost:8128/ will redirect you to the ongoing invokation
See also http://localhost:8128/invokation for invokation list
""")
def cmd_invoke(prob=None, imanager=None, judge=None, ui=None, argv=None):
    import threading
    
    solutions = argv
    test_list = prob.get_test_list()
    test_indices = [i + 1 for i in range(len(test_list))]
    
    if solutions == ["@all"]:
        solutions = os.listdir(prob.relative("solutions"))
        solutions.sort()
    
    uid, invokation = imanager.new_invokation(judge, solutions, test_indices)
    ithread = threading.Thread(target=invokation.start)
    ithread.start()
            
    ui.mode_invokation(uid, imanager)
    ui.start()
        
    ithread.join()
    return 0

@cmd(want=["prob-old", "ui"], arg="testview", manual="Show test data",
     long_help = """Examine the tests
     
Connect to http://localhost:8128/ or localhost::8128/test_view
To browse the tests

You probably want run "pmaker tests" prior this command.
""")
def cmd_testview(prob=None, ui=None):
    ui.mode_testview()
    ui.start()
    return 0


@cmd(want=["argv"], arg="help", manual="Show this help")
def cmd_help(argv=None):
    if len(argv) == 1:
        for (cmd, desc, hlp) in help_info:
            if cmd == argv[0]:
                print("Help for {}".format(cmd))
                print("=" * len("Help for {}".format(cmd)))
                print(hlp)
                
                return 0

        print("Failed to find help for the {}".format(cmd))
        return 1

    if len(argv) > 2:
        print("Invalid help topic")
        return 1
        
    import pmaker
    print("PMaker v{}".format(pmaker.__version__))
    print("")
    print("Usage:")
    print("======")

    max_cmd = 0
    for (cmd, desc, hlp) in help_info:
        max_cmd = max(max_cmd, len(cmd))
    
    for (cmd, desc, hlp) in help_info:
        print(cmd + " " * (3 + max_cmd - len(cmd)) + desc)

    print("")
    print("For more information use help <subcommand>")

@cmd(arg="--help")
def cmd_help2():
    return cmd_help([])

@cmd(want=["prob-old", "imanager", "judge", "ui", "argv"], arg="invoke",
     manual="Invoke specified solutions",
     long_help="""Invokes the specified solutions

Usage: pmaker invoke [list-of-solutions],
or     pmaker invoke @all

The link http://localhost:8128/ will redirect you to the ongoing invokation
See also http://localhost:8128/invokation for invokation list
""")
def cmd_invoke(prob=None, imanager=None, judge=None, ui=None, argv=None):
    import threading
    
    solutions = argv
    test_list = prob.get_test_list()
    test_indices = [i + 1 for i in range(len(test_list))]
    
    if solutions == ["@all"]:
        solutions = os.listdir(prob.relative("solutions"))
        solutions.sort()
    
    uid, invokation = imanager.new_invokation(judge, solutions, test_indices)
    ithread = threading.Thread(target=invokation.start)
    ithread.start()
            
    ui.mode_invokation(uid, imanager)
    ui.start()
        
    ithread.join()
    return 0

@cmd(want=["prob", "argv"], arg="clean", manual="Wipe data",
     long_help = """Wipes all generated data and cache, except invokations.

Add "--mrpropper" flag to wipe invokations as well.
""")
def cmd_clean(prob=None, argv=None):
    if not argv in [[], ["--mrpropper"]]:
        print("Unrecognized arg")

    prob.wipe(mrpropper=(argv == ["--mrpropper"]))
    return 0

def main():
    argv = sys.argv[1:]
    if len(argv) == 0:
        argv = ["--help"]

    for (matcher, command) in commands_list:
        if (matcher == argv[0]):
            return command(argv[1:])

    print("There is no such command")
    argv = ["--help"]

    for (matcher, command) in commands_list:
        if (matcher == argv[0]):
            return command(argv[1:])
