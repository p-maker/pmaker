import sys, os, os.path, configparser, subprocess, shutil, tempfile, time

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
