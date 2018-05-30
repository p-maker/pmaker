import json
import sqlite3
import sys, os, os.path

from pmaker.judge import new_judge
import pmaker.ui.web.web
import pmaker.problem

import tornado.escape
import tornado.ioloop
import tornado.httpserver
import tornado.web

import jinja2, html

import uuid
import time
import subprocess

import threading

from pkg_resources import resource_string
from pmaker.invocation_manager import new_invocation_manager

class _BaseHandler(tornado.web.RequestHandler):
    template_cache = dict()

    def __init__(self, *args, **kwargs):
        self._db_name = kwargs["db"]
        del kwargs["db"]
        self._judge = kwargs["judge"]
        del kwargs["judge"]
        super().__init__(*args, **kwargs)

    def send_data(self, data, code=200):
        self.set_status(code)
        self.finish(bytes(data, 'utf-8'))
    
    def render(self, template, **kwargs):
        if not template in _BaseHandler.template_cache:
            package_name = 'pmaker.ui.web'
            obj_name = template
            
            if template.startswith("server/"):
                package_name = 'pmaker.server.templates'
                obj_name = template[len("server/"):]

            data = resource_string(package_name, obj_name).decode("utf-8")
            _BaseHandler.template_cache[template] = jinja2.Template(data)

        template = _BaseHandler.template_cache[template]
        self.send_data(template.render(**kwargs, **self.get_template_namespace()))

    def database(self):
        return sqlite3.connect(self._db_name)
        
    def get_template_namespace(self):
        import builtins, os, os.path
        mp = builtins.__dict__
        mp["shortly"] = pmaker.ui.web.web.get_file_preview
        mp["escape"]  = html.escape

        mp["exists"] = os.path.exists
        return mp

    def get_login(self, db):
        r = self.get_secure_cookie("login")
        if r == None or r == b"":
            return None
        return str(r, 'utf-8')
        
class _RootHandler(_BaseHandler):
    def get(self):
        with self.database() as db:
            c = db.cursor()
            
            login = self.get_login(db)
            probs = []
            if login != None:
                probs = c.execute('select name, uid from problems')
            self.render("server/root.html", login=login, probs=probs)

class _LoginHandler(_BaseHandler):
    def get(self):
        self.render("server/login.html")

    def post(self):
        login = self.get_argument("login", "")
        passwd = self.get_argument("password", "")

        with self.database() as db:
            c = db.cursor()
            lst = c.execute('select user, password from users where user = ? and password = ?', (login,passwd)).fetchall()

            if len(lst) != 0:
                self.set_secure_cookie("login", login)
                self.redirect("/")
            else:
                self.redirect("/login")

class _LogoutHandler(_BaseHandler):
    def get(self):
        self.set_secure_cookie("login", "")
        self.redirect("/")

class _StyleHandler(_BaseHandler):
    styles = None
    def get(self):
        if _StyleHandler.styles == None:
            s1 = resource_string("pmaker.ui.web", "style.css").decode("utf-8")
            s2 = resource_string("pmaker.server.templates", "style.css").decode("utf-8")
            _StyleHandler.styles = s1 + s2

        self.set_header("Content-Type", "text/css; charset=UTF-8")
        self.send_data(_StyleHandler.styles)

class _ProblemWizardHandler(_BaseHandler):
    def get(self):
        with self.database() as db:
            login = self.get_login(db)
            if login == None:
                self.redirect("/login")
                return

            self.render("server/prob_wizard.html", login=login)

    def post(self):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
        
        name = self.get_body_argument("name", "")
        url  = self.get_body_argument("url", "")
        user = self.get_body_argument("user", "")
        pswd = self.get_body_argument("password", "")

        uid = str(uuid.uuid4())
        with self.database() as db:
            c = db.cursor()
            try:
                c.execute('''insert into problems VALUES (?, ?)''', (name, uid))
            except:
                self.send_data("Failed to create problem, check that name is unique and repeat", code=500)
                return

            os.makedirs("repo/{}".format(uid))
            with open("repo/{}/cfg".format(uid), "w") as fp:
                json.dump({"name": name, "url": url, "user": user, "password": pswd}, fp)

            thread = threading.Thread(target=run_clone, args=(uid,"repo/{}".format(uid), url, user, pswd))
            thread.start()
            
            self.redirect("/p/{}".format(uid))

def has_problem(db, uid):
    c = db.cursor()
    c.execute('''select name from problems where uid = ?''', (uid,))
    a = c.fetchall()
    if len(a) == 0:
        return None
    return a[0][0]
    
class _ProblemCoreHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + uid

            cfg = None
            with open(dr + "/cfg") as fp:
                cfg = json.load(fp)
            
            status = None
            try:
                with open(dr + "/lock") as fp:
                    status = fp.read()
            except:
                pass

            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            def make_ref(to, where=None):
                if to == None:
                    return "<i>none</i>"
                
                path = to
                if where:
                    path = where + "/" + to
                return '<a href=/p/{}/fs/{} class="action">{}</a>'.format(uid, path, to)
            self.render("server/prob_view.html", name=name, status=status, cfg=cfg, uid=uid, prob=prob, make_ref=make_ref)

class _ProblemDeleteHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            c = db.cursor()
            c.execute('''delete from problems where uid = ?''', (uid,))
            self.redirect("/")

class _ProblemFsViewHandler(_BaseHandler):
    def get(self, uid, path):
        with self.database() as db:
            path = "/" + path

            if path != '/' and path.endswith("/"):
                path = path[:-1]
                
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            if path == "/.git" or path.startswith("/.git/") or "//" in path or path == "/work" or path.startswith("/work/"):
                self.send_data("404 not found", code=404)
                return

            name = has_problem(db, uid)
            if name == None:
                self.redirect("/")
                return
            
            dr = "repo/{}".format(uid)

            try:
                if os.path.isdir(dr + "/git" + path):
                    listing = os.listdir(dr + "/git" + path)
                    listing.sort()
                    if path == '/':
                        if '.git' in listing:
                            listing.remove('.git')
                        if 'work' in listing:
                            listing.remove('work')
                    if not path.endswith('/'):
                        path = path + '/'
                    self.render("server/prob_dirlisting.html", name=name, uid=uid, listing=listing, path=path)
                    return
                print(dr + "/git" + path)
                
                if os.path.isfile(dr + "/git" + path):
                    data = None
                    with open(dr + "/git" + path) as fp:
                        data = fp.read()

                    self.set_header("Content-Type", "text/plain; charset=UTF-8")
                    self.send_data(data)
                    return
                self.redirect("/p/{}".format(uid))
            except:
                raise
                self.redirect("/p/{}".format(uid))

class _ProblemTestViewHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + uid

            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)

            testset = None
            try:
                testset = prob.get_testset(check_only=True)
            except:
                prob.set_judge(self._judge)
                run_synchronized(uid, dr, prob.get_testset, "[script invocation]")
                pass
            self.render("server/prob_testview.html", name=name, uid=uid, prob=prob, testset=testset)

class _ProblemTestDataHandler(_BaseHandler):
    def __init__(self, *args, **kwargs):
        self.is_input = kwargs["input"]
        del kwargs["input"]
        super().__init__(*args, **kwargs)
        
    def get(self, uid, index):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            try:
                index = int(index)
            except:
                self.send_data("404", code=404)
                return
            
            dr = "repo/" + uid

            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)

            testset = None
            try:
                testset = prob.get_testset(check_only=True)
            except:
                pass

            if testset == None or testset.by_index(index, noraise=True) == None:
                self.send_data("404", code=404)

            test = testset.by_index(index)
            self.send_data("TODO", code=200)

class _ProblemUpdateHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            thread = threading.Thread(target=run_pull, args=(uid,"repo/{}".format(uid)))
            thread.start()
            self.redirect("/p/{}".format(uid))

managers = dict()

def get_manager(uid, prob):
    global managers
    if not uid in managers:
        managers[uid] = new_invocation_manager(prob, prob.relative("work", "invocations"))
    return managers[uid]

class _ProblemInvocationListHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + str(uid)
            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)

            manager = get_manager(uid, prob)

            invocations = manager.list_invocations()
            active      = manager.list_active()

            def is_active(name):
                return name in active

            def get_solutions(invocation):
                try:
                    return " ".join(invocation.get_solutions())
                except:
                    return "<span style='color: red'>Data not available</span>"

            def make_url(no):
                return "/p/{}/invocations/{}".format(uid, no)
                
            invocations.sort()
            invocations.reverse()
            
            self.render("invocation_list.html", prob=prob, get_solutions=get_solutions, invocations=invocations, active=is_active, imanager=manager, show_new=["/p/{}/invocations/new".format(uid), "/p/{}/update_all".format(uid)], make_url=make_url)
                

class _ProblemNewInvocationHandler(_BaseHandler):
    def get(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + str(uid)
            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)
                return
            
            solutions = []
            if os.path.isdir(prob.relative("solutions")):
                solutions = os.listdir(prob.relative("solutions"))
            self.render("server/new_invocation.html", prob=prob, name=name, uid=uid, solutions=solutions)
    def post(self, uid):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return
            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + str(uid)
            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)
                return

            prob.set_judge(self._judge)
            solutions = []
            if os.path.isdir(prob.relative("solutions")):
                solutions = os.listdir(prob.relative("solutions"))

            selected = []
            for sol in solutions:
                if self.get_argument("chkb_" + sol, "") != "":
                    selected.append(sol)

            if selected != []:
                manager = get_manager(uid, prob)
                manager.prob.set_judge(self._judge)
                no, invocation = manager.new_invocation(self._judge, solutions, [i for i in range(1, prob.get_testset(check_only=False).size() + 1)])

                self.redirect("/p/{}/invocations/{}".format(uid, no))
                threading.Thread(target=invocation.start).start()
                return
            self.redirect("/p/{}/invocations/new".format(uid))

class _ProblemInvocationViewHandler(_BaseHandler):
    def get(self, uid, no):
        with self.database() as db:
            if self.get_login(db) == None:
                self.redirect("/login")
                return

            
            name = has_problem(db, uid)
            if name == None:
                self.send_data("404 Not Found", code=404)
                return

            dr = "repo/" + str(uid)
            prob = None
            if os.path.isfile(dr + "/git/problem.cfg"):
                try:
                    prob = pmaker.problem.new_problem(dr + "/git")
                except:
                    pass

            if prob == None:
                self.send_data("404", code=404)
                return

            prob.set_judge(self._judge)
            invocation = None
            try:
                invocation = get_manager(uid, prob).get_invocation(int(no))
            except:
                raise                        
            
            if invocation == None:
                self.send_data("404", code=404)
                return

            from pmaker.ui.web.web import render_invocation
            render_invocation(self.render, "invocation.html", get_manager(uid, prob), int(no), prob)
            
            
def acquire_lock(uid, dr, reason):
    retry = 0
    while retry < 10:
        try:
            fd = os.open(dr + "/lock", os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_EXCL)
            with os.fdopen(fd, "w") as fp:
                fp.write(reason)
        except:
            retry += 1
            time.sleep(1) # try again later

def release_lock(uid, dr):
    os.remove(dr + "/lock")

class DirLock:
    def __init__(self, uid, dr, reason):
        self.uid = uid
        self.dr  = dr
        acquire_lock(self.uid, self.dr, reason)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        release_lock(self.uid, self.dr)
    
def run_clone(uid, dr, url, user, pswd):
    try:
        with DirLock(uid, dr, "git clone") as lock:
            subprocess.check_call(['git', 'clone', url, dr + '/git'], timeout=30)
    except:
        import traceback
        traceback.print_exc()

def run_pull(uid, dr):
    try:
        with DirLock(uid, dr, "git pull") as lock:
            subprocess.check_call(['git', 'pull', 'origin', 'master'], cwd=dr + "/git", timeout=30)
    except:
        import traceback
        traceback.print_exc()


def run_synchronized(uid, dr, func, reason):
    def do_run():
        print("123")
        try:
            with DirLock(uid, dr, reason) as lock:
                print("GOT LOCK")
                func()
                print("EXIT-0.5")
            print("EXIT")
        except:
            import traceback
            traceback.print_exc()

    threading.Thread(target=do_run).start()
        
def run_server(config, secret, home, db, judge):
    def extra(**kwargs):
        res = {"db": db, "judge": judge}
        res.update(**kwargs)
        return res
        
    SYS_INFO = extra()
        
    app = tornado.web.Application(
        [
            (r"/", _RootHandler, SYS_INFO),
            (r"/login", _LoginHandler, SYS_INFO),
            (r"/logout", _LogoutHandler, SYS_INFO),
            (r"/newprob", _ProblemWizardHandler, SYS_INFO),
            (r"/p/([^./]*)/?",    _ProblemCoreHandler, SYS_INFO),
            (r"/delete/([^./]*)",    _ProblemDeleteHandler, SYS_INFO),
            (r"/p/([^./]*)/tests",    _ProblemTestViewHandler, SYS_INFO),
            (r"/p/([^./]*)/tests/([^./]*)/input",    _ProblemTestDataHandler, extra(input=True)),
            (r"/p/([^./]*)/tests/([^./]*)/output",    _ProblemTestDataHandler, extra(input=False)),
            (r"/p/([^./]*)/up/?",    _ProblemUpdateHandler, SYS_INFO),
            (r"/p/([^./]*)/fs/(.*)",    _ProblemFsViewHandler, SYS_INFO),
            (r"/p/([^./]*)/invocations/?",   _ProblemInvocationListHandler, SYS_INFO),
            (r"/p/([^./]*)/invocations/new",   _ProblemNewInvocationHandler, SYS_INFO),
            (r"/p/([^./]*)/invocations/([^./]*)",   _ProblemInvocationViewHandler, SYS_INFO),
            (r"/static/style.css", _StyleHandler, SYS_INFO)
        ],
        cookie_secret=secret)

    address = "127.0.0.1"
    port = 8080
    num_threads = 1
    
    if "address" in config:
        address = config["address"]

    if "port" in config:
        port = config["port"]

    if "num_threads" in config:
        num_threads = config["num_threads"]
        
    server = tornado.httpserver.HTTPServer(app)
    server.bind(port, address=address)

    print("Serving on {}:{}".format(address, str(port)))
    
    server.start(num_threads)
    tornado.ioloop.IOLoop.current().start()

def main():
    if sys.argv[1:] == ["makedb"]:
        with sqlite3.connect("data.db") as db:
            c = db.cursor()
            c.execute('''create table if not exists users
                       (user text not null, password text not null, unique (user))''')

            c.execute('''create table if not exists problems
                        (name text not null, uid text not null, unique (name), unique (uid))''')
        print("OK")
        return

    if len(sys.argv[1:]) == 3 and sys.argv[1] == "adduser":
        with sqlite3.connect("data.db") as db:
            c = db.cursor()
            c.execute('''insert or replace into users values (?, ?)''', (sys.argv[2], sys.argv[3]))
        print("OK")
        return

    if len(sys.argv[1:]) != 0:
        print("Command not understood")
        return
    
    config = None
    with open("pserver.cfg", "r") as fp:
        config = json.load(fp)

    secret = None
    with open("secret.txt", "r") as fp:
        secret = fp.read()
        
    home = os.path.realpath("./work")

    with new_judge() as judge:
        run_server(config, secret, home, "data.db", judge)
