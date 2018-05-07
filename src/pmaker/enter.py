import sys, os, os.path, configparser, subprocess, shutil, tempfile, time, html

from concurrent.futures import ThreadPoolExecutor as Pool

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

def main():
    prob = lookup_problem(os.path.realpath("."))
    if not prob:
        error("fatal: couldn't find problem")

    cmd = sys.argv[1] if len(sys.argv) >= 2 else None
    
    if (cmd == "tests" or cmd == None):
        prob.gen_tests()
    if cmd == "tests2":
        from pmaker.judge import new_judge
        with new_judge() as judge:
            prob.gen_tests_new(judge)
    elif cmd == "invokation-list":
        from pmaker.invokation_manager import new_invokation_manager
        from pmaker.ui.web.web import WebUI

        imanager = new_invokation_manager(prob, prob.relative("work", "invokations"))
        
        ui = WebUI(prob)
        ui.mode_invokation_list(imanager)
        ui.start()
    elif cmd == "invoke":
        solutions = sys.argv[2:]
        test_list = prob.get_test_list()
        test_indices = [i + 1 for i in range(len(test_list))]

        if solutions == ["@all"]:
            solutions = os.listdir(prob.relative("solutions"))
            solutions.sort()
        
        from pmaker.judge import new_judge
        from pmaker.invokation_manager import new_invokation_manager
        from pmaker.ui.web.web import WebUI
        import threading

        imanager = new_invokation_manager(prob, prob.relative("work", "invokations"))
        
        with new_judge() as judge:
            uid, invokation = imanager.new_invokation(judge, solutions, test_indices)
            ithread = threading.Thread(target=invokation.start)
            ithread.start()
            
            ui = WebUI(prob)
            ui.mode_invokation(uid, imanager)
            ui.start()
            
            ithread.join()
    elif cmd == "invoke-old":
        solutions = sys.argv[2:]
        test_list = prob.get_test_list()
        timelimit = prob.timelimit

        if len(solutions) == 0:
            error("fatal: please specify solutions to run")
        
        for sol in solutions:
            prob.compile(os.path.join("solutions", sol))

        if not prob.checker:
            error("fatal: checker is not available")
            
        os.makedirs(os.path.join("work", "temp"), exist_ok=True)
        def judge(solution, test):
            input_name = os.path.join("work", "tests", "%03d" % test)
            answer_name = os.path.join("work", "tests", "%03d.a" % test)
            
            with tempfile.NamedTemporaryFile(prefix="out_", dir=os.path.join("work", "temp")) as output:
                with open(input_name, "rb") as inp:
                    tm0 = time.time()

                    try:
                        ret = subprocess.run([os.path.join("work", "compiled", "solutions", solution)], stdin=inp, timeout=(2 * prob.timelimit), stdout=output).returncode
                    except subprocess.TimeoutExpired:
                        return "HARD-TL"
                    tm1 = time.time()

                    taken = "%.2f" % (tm1 - tm0)
                    
                    if (ret != 0):
                        return "RE ({})".format(taken)

                    checking = subprocess.run([os.path.join("work", "compiled", prob.checker), input_name, answer_name, output.name], stdout=subprocess.PIPE, universal_newlines=True)
                    if checking.returncode != 0:
                        return "WA ({})".format(taken)

                    if (tm1 - tm0 <= prob.timelimit):
                        return "OK ({})".format(taken)
                    
                    return "TL ({})".format(taken)

            
        pool = Pool(max_workers=3)
        results = [[pool.submit(judge, solutions[j], i + 1) for j in range(len(solutions))] for i in range(len(test_list))]

        import http.server
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/":
                    self.send_response(404)
                    return
                
                self.send_response(200)

                self.send_header('Content-type','text/html')
                self.end_headers()

                def write(s):
                    self.wfile.write(bytes(s, "utf-8"))
                
                write("""
<!DOCTYPE html>
<html>
<head>
<style>
table {
  border-collapse: collapse;
}
td {
  padding: 2px;
}
.padd_line {
  padding: 0.001px;
}
.cell, .centered {
  text-align: center;
}
.cell_OK {
  background-color: lightgreen;
}
.cell_RJ {
  background-color: #fb6837;
}
</style>
</head>
<body>
<table border>
""")
                write("<tr><td>test</td>\n")
                write("".join(["<td>{}</td>".format(sol) for sol in solutions]))
                write("</tr>\n")

                prev_group = None
                for (test, index) in zip(test_list, range(1, 1001)):
                    if prev_group != None and prev_group != test.get_group():
                        write("<td class=\"padd_line\"></td>")
                    prev_group = test.get_group()
                        
                    write("<tr>")
                    if test.get_group() != None:
                        write("<td>{} ({})</td>".format(index, test.get_group()))
                    else:
                        write("<td>{}</td>".format(index))

                    for j in range(len(solutions)):
                        res = None
                        if results[index - 1][j].done():
                            res = results[index - 1][j].result()
                        else:
                            res = "pending"
                        write("<td class=\"cell {}\">{}</td>".format("cell_" + res.split(" ")[0], res))
                    
                    write("</tr>")

                write("""
</table>
</body>
</html>
""")
                return

        server = http.server.HTTPServer(("localhost", 8128), Handler)
        print("please connect to http://localhost:8128")
        server.serve_forever()
    elif cmd == "view-tests" or cmd == "testview" or cmd == "test-view":
        from pmaker.ui.web.web import WebUI
        
        ui = WebUI(prob)
        ui.mode_testview()
        ui.start()
