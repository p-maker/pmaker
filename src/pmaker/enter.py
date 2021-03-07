import sys, os, os.path, configparser, subprocess, shutil, tempfile, time

import pmaker.problem

def error(msg):
    print(msg)

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
                from pmaker.invocation_manager import new_invocation_manager
                
                __kwargs["imanager"] = new_invocation_manager(__kwargs["prob"], __kwargs["prob"].relative("work", "invocations"))
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

@cmd(want=["prob", "imanager", "judge", "ui", "argv"], arg="invoke",
     manual="Invoke specified solutions",
     long_help="""Invokes the specified solutions

Usage: pmaker invoke [list-of-solutions],
or     pmaker invoke @all

You will probably want to run "pmaker tests" prior this command.

The link http://localhost:8128/ will redirect you to the ongoing invocation
See also http://localhost:8128/invocation for invocation list
""")
def cmd_invoke(prob=None, imanager=None, judge=None, ui=None, argv=None):
    import threading

    prob.set_judge(judge)    
    solutions = argv
    test_cnt = prob.get_testset().size()
    test_indices = list(range(1, test_cnt + 1))
    
    if solutions == ["@all"]:
        solutions = os.listdir(prob.relative("solutions"))
        solutions.sort()
    
    uid, invocation = imanager.new_invocation(judge, solutions, test_indices)
    ithread = threading.Thread(target=invocation.start)
    ithread.start()
            
    ui.mode_invocation(uid, imanager)
    ui.start()
        
    ithread.join()
    return 0


@cmd(want=["prob", "argv"], arg="run",
     manual="Run the solution interactively in CLI",
     long_help="""Invokes the specified solution for interactive communication
Usage: pmaker run <solution_name>

Compiles and interactively runs the specified solution name in the CLI.

Use stdin and stdout to communicate with the solution.

Warning: solution is runned without been sandboxed.
""")
def cmd_run(prob=None, argv=None):
    import subprocess

    if (len(argv) != 1):
        print("usage: pmaker run <solution_name>")
        return 1

    sol = argv[0]
    
    need_compile = False
    try:
        prob.compile("solutions", sol, check_only=True)
    except pmaker.problem.ProblemJobOutdated:
        need_compile = True

    if need_compile:
        from pmaker.judge import new_judge
        with new_judge() as judge:
            prob.set_judge(judge)
            prob.compile("solutions", sol)
    
    prob.compile("solutions", sol)
    path = prob.compilation_result("solutions", sol)
    
    res = subprocess.run(path, universal_newlines=True)
    print("Exitted with code {}".format(res.returncode), file=sys.stderr)
    return res.returncode


@cmd(want=["prob", "imanager", "ui"], arg="invocation-list",
     manual="Show previous invocations",
     long_help="""Starts the web server so you can examine previous invocations
     
See http://localhost:8128/invocation for invocation list
And http://localhost:8128/invocation/<invocation_no> for the previous invocation
     """)
def cmd_invocation_list(prob=None, imanager=None, ui=None):
    ui.mode_invocation_list(imanager)
    ui.start()
    return 0

@cmd(want=["prob", "ui"], arg="testview", manual="Show test data",
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

@cmd(want=["prob", "argv"], arg="clean", manual="Wipe data",
     long_help = """Wipes all generated data and cache, except invocations.

Add "--mrpropper" flag to wipe invocations as well.
""")
def cmd_clean(prob=None, argv=None):
    if not argv in [[], ["--mrpropper"]]:
        print("Unrecognized arg")

    prob.wipe(mrpropper=(argv == ["--mrpropper"]))
    return 0

@cmd(want=["prob"], arg="make_valuer")
def cmd_valuer(prob=None):
    #print("# # # generated with pmaker # # #")
    print("""
global {
    stat_to_judges 1;
    stat_to_users 1;
}""")

    tests = prob.get_testset()
    group_info = prob.get_testset().group_info()
    
    samples = []
    offline = []
    not_offline = []
    line = prob._parser.get("scoring", "samples", fallback=None)
    if line:
        samples = list(map(lambda s: s.strip(), line.split(";")))
        
    line = prob._parser.get("scoring", "offline", fallback=None)
    if line:
        offline = list(map(lambda s: s.strip(), line.split(";")))
    
    test_score_list = ['0' for i in range(tests.size())]
    sum_score = 0
    sum_user_score = 0
    
    for gr in sorted(group_info.keys(), key=int):
        if len(group_info[gr]) != 1:
            print("Group {} is not contigious".format(gr), file=sys.stderr)
            sys.exit(1)

        test_score_list[group_info[gr][0][1] - 1] = prob._parser.get("scoring", "score_" + gr, fallback="0")
        if not gr in offline:
            not_offline.append(gr)
    
    for gr in sorted(group_info.keys(), key=int):
        sc = int(prob._parser.get("scoring", "score_" + gr, fallback="0"))
        sum_score += sc
        if not gr in offline:
            sum_user_score += sc

        req = ""
        line = prob._parser.get("scoring", "require_" + gr, fallback=None)
        if line:
            req = "requires {};".format(",".join(map(lambda s: s.strip(), line.split(";"))))

        print("group %s {" % gr)
        print("    tests %d-%d;" % (group_info[gr][0][0], group_info[gr][0][1]))
        print("    score %d;" % sc)

        if gr in offline:
            print("    offline;")

        if len(not_offline) != 0 and gr == not_offline[-1]:
            print("    sets_marked_if_passed %s;" % ", ".join(not_offline))
            
        print("    %s" % req)
        print("}")
    
    print('# test_score_list="{}"'.format(" ".join(test_score_list)))
    open_tests = []
    for gr in sorted(group_info.keys(), key=int):
        if gr in samples:
            open_tests.append("%d-%d:full" % (group_info[gr][0][0], group_info[gr][0][1]))
        elif gr in offline:
            open_tests.append("%d-%d:hidden" % (group_info[gr][0][0], group_info[gr][0][1]))
        else:
            open_tests.append("%d-%d:brief" % (group_info[gr][0][0], group_info[gr][0][1]))
    if open_tests:
        print('# open_tests="{}"'.format(",".join(open_tests)))
    print('# full_score=%d' % sum_score)
    print('# full_user_score=%d' % sum_user_score)

def main():
    try:
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
    except KeyboardInterrupt as ex:
        print("Interrupted")
        sys.exit(0)
