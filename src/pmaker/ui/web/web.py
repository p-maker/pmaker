import http.server
import html
import jinja2
import sys
import pkg_resources

import pmaker

class WebUI:
    def __init__(self, prob):
        self.port = 8128
        self.prob = prob
        self.default = "/dashboard"
        self.template_cache = dict()
        self.imanager = None
        
        webui = self
        
        class WebHandler(http.server.BaseHTTPRequestHandler):
            def write_bytes(self, bts):
                try:
                    self.wfile.write(bts)
                except BrokenPipeError as ex:
                    pass # the web-browser likely got disconnected

            def write_string(self, s):
                try:
                    self.wfile.write(bytes(s, "utf-8"))
                except BrokenPipeError as ex:
                    pass # the web-browser likely got disconnected

            def get_file_preview(path, limit=512, linelimit=10):
                try:
                    with open(path, "r") as f:
                        s = f.read(limit)
                
                        trail = False
                
                        if len(s) == limit:
                            trail = True
                    
                        lines = s.split("\n")
                        if linelimit != -1 and len(lines) > linelimit:
                            s = "\n".join(lines[0:linelimit])
                            trail = True
                    
                        if trail:
                            s += "..."
                    
                        pre  = '<span class="data_text">'
                        post = '<span class="data_text">'
                        if s == "":
                            return '<span class="data_text data_empty">(empty)</span>'
                        return pre + html.escape(s).replace("\n","<br>") + post
                except:
                    (_, ex, _) = sys.exc_info()
                    return "<span style=\"data_error\">failed to read: {}</span>".format(ex)

            def get_template_namespace(self):
                import builtins, os, os.path
                mp = builtins.__dict__
                mp["shortly"] = WebHandler.get_file_preview
                mp["escape"]  = html.escape

                mp["exists"] = os.path.exists
                
                return mp
                
            def redirect(self, new_url, code=302):
                self.send_response(code)
                self.send_header("Location", new_url)
                self.end_headers()
        
            def render(self, template, **kwargs):
                if not template in webui.template_cache:
                    template_data = pkg_resources.resource_string(__name__, template).decode("utf-8")
                    webui.template_cache[template] = jinja2.Template(template_data)

                data = webui.template_cache[template].render(**kwargs)
                self.send_response(200)
                self.end_headers()
                self.write_string(data)

            def send_data(self, data, code=200):
                self.send_response(code)
                self.end_headers()
                self.write_bytes(data)

            def send_txt_data(self, data, code=200):
                self.send_response(code)
                self.end_headers()
                self.write_string(data)
                
            def send_404(self):
                self.send_data(pkg_resources.resource_string(__name__, "404.html"), code=404)
            
            def do_GET(self):
                parts = self.path[1:].split('/')
                if len(parts) >= 1 and parts[-1] == '':
                    parts = parts[:-1]
                
                if parts == []:
                    self.redirect(webui.default)
                    return
                if parts == ["static", "style.css"]:
                    self.send_data(pkg_resources.resource_string(__name__, "style.css"))
                    return
                if parts == ["test_view"]:
                    tests = webui.prob.get_testset()
                    group_info = tests.group_info()

                    def __groupcomparator(obj):
                        info = obj[1]
                        if len(info) == 0:
                            return +100000000000
                        else:
                            return info[0][0]
                    
                    self.render("test_view.html", prob=webui.prob, tests=tests, group_info=group_info, **self.get_template_namespace(), __groupcomparator=__groupcomparator)
                    return

                if parts[:2] == ["test_view", "show_test"] and len(parts) == 4 and parts[3] in ["input", "output"]:
                    try:
                        test = webui.prob.get_testset().by_index(int(parts[2]), noraise=True)
                        if not test:
                            self.send_404()
                            return

                        self.render("test_verbose.html", prob=webui.prob, test=test, test_no=parts[2], part=parts[3], **self.get_template_namespace())
                        return
                    except ValueError:
                        self.send_404()
                        return

                if parts == ["invocation"] and webui.imanager != None:
                    invocations = webui.imanager.list_invocations()
                    active      = webui.imanager.list_active()

                    def is_active(name):
                        return name in active

                    def get_solutions(invocation):
                        try:
                            return " ".join(invocation.get_solutions())
                        except:
                            return "<span style='color: red'>Data not available</span>"

                    invocations.sort()
                    invocations.reverse()
                    self.render("invocation_list.html", prob=webui.prob, get_solutions=get_solutions, invocations=invocations, active=is_active, imanager=webui.imanager)
                    return
                    
                if parts[:1] == ["invocation"] and len(parts) == 2 and webui.imanager != None:
                    the_invocation = None
                    uid = None
                    try:
                        uid = int(parts[1])
                        the_invocation = webui.imanager.get_invocation(uid)
                    except:
                        self.send_404()
                        return
                    
                    if the_invocation == None:
                        self.send_404()
                        return
                    
                    solutions     = the_invocation.get_solutions()
                    test_indices  = the_invocation.get_tests()

                    def render_extras(i, j, hard_tl=False, tl_plus=False):
                        if the_invocation.get_descriptor(i, j).is_final():
                            (tm, mem) = the_invocation.get_descriptor(i, j).get_rusage()
                            display_tm = None
                            if tm == None:
                                display_tm = "?"
                            elif hard_tl:
                                display_tm = '<span class="hard_tl">inf</span>'
                            elif tl_plus:
                                display_tm = '<span class="was_tl">%.1f</span>' % (tm / 1000)
                            else:
                                display_tm = '%.1f' % (tm / 1000)

                            display_mem = None
                            if mem == None:
                                display_mem = "?"
                            else:
                                display_mem = "%.0f mb" % (mem / 1000)
                            return '<span class="invocation_stat">(%s, %s)</span>' % (display_tm, display_mem)
                        return ""

                    def render_cell(i, j):
                        hard_tl = False
                        tl_plus   = False

                        from pmaker.invocation import InvokationStatus
                        res = the_invocation.get_result(i, j)
                        if res == InvokationStatus.TL:
                            hard_tl = True
                        if res == InvokationStatus.TL_OK:
                            res = InvokationStatus.TL
                            tl_plus = True
                        elif res.is_tl():
                            res = res.undo_tl()
                            tl_plus = True

                        internal = ''
                        if len(res.name) >= 3:
                            internal = '<span class="iverdict iverdict_long iverdict_{}">{}</span>'.format(res.name, res.name)
                        else:
                            internal = '<span class="iverdict iverdict_{}">{}</span>'.format(res.name, res.name)
                        extras = ""
                        if res != InvokationStatus.INCOMPLETE:
                            extras   = render_extras(i, j, hard_tl=hard_tl, tl_plus=tl_plus)
                        return '<td onclick="open_cell({},{})" class="invocation_cell_{}">{} {}</td>'.format(i, j, res.name, internal, extras)

                    def render_stats():
                        from collections import OrderedDict
                        from pmaker.invocation import InvokationStatus
                        
                        data = OrderedDict()
                        class SimpleStruct:
                            def __init__(self):
                                self.time = 0
                                self.mem  = 0
                                self.verdicts = []                        
                        
                        def do_update(group, sol, tm, mem, verdict):
                            if not group in data:
                                data[group] = [SimpleStruct() for _ in range(len(solutions))]
                            if tm != None:
                                data[group][sol].time = max(tm, data[group][sol].time)
                            if mem != None:
                                data[group][sol].mem  = max(mem, data[group][sol].mem)
                                
                            if verdict in [InvokationStatus.RUNNING, InvokationStatus.CHECKING]:
                                verdict = InvokationStatus.PENDING
                            if verdict.name != "RUNNING" and verdict.name != "CHECKING" and not verdict in data[group][sol].verdicts:
                                data[group][sol].verdicts.append(verdict)

                        for i in range(len(solutions)):
                            for j in range(len(test_indices)):
                                result = the_invocation.get_result(i, j)
                                (tm, mem) = the_invocation.get_descriptor(i, j).get_rusage()
                                do_update("", i, tm, mem, result)
                                if webui.prob.get_testset().by_index(test_indices[j]).has_group():
                                    do_update(webui.prob.get_testset().by_index(test_indices[j]).get_group(), i, tm, mem, result)

                        for (key, value) in data.items():
                            for i in range(len(solutions)):
                                value[i].verdicts.sort()
                        return data.items()
                    
                    from pmaker.invocation import InvokationStatus
                    self.render("invocation.html", prob=webui.prob, invocation=the_invocation, solutions=solutions, test_indices=test_indices, uid=uid, render_stats=render_stats, render_cell=render_cell, InvokationStatus=InvokationStatus, **self.get_template_namespace())
                    return

                if len(parts) == 4 and parts[0] == "invocation" and parts[2] == "compilation" and webui.imanager != None:
                    the_invocation = None
                    uid = None
                    sol_id = None
                    solution = None
                    
                    try:
                        uid = int(parts[1])
                        sol_id = int(parts[3])
                        the_invocation = webui.imanager.get_invocation(uid)
                        solution = the_invocation.get_solutions()[sol_id]
                    except:
                        self.send_404()
                        return
                    
                    if the_invocation == None:
                        self.send_404()
                        return

                    self.render("invocation_compilation.html", uid=uid, solution=solution, sol_id=sol_id, invocation=the_invocation, **self.get_template_namespace())
                    return
                
                if len(parts) == 5 and parts[0] == "invocation" and parts[2] == "result" and webui.imanager != None:
                    the_invocation = None
                    uid      = None
                    sol_id   = None
                    test_id  = None
                    test     = None
                    the_test = None
                    solution = None
                    
                    try:
                        uid     = int(parts[1])
                        sol_id  = int(parts[3])
                        test_id = int(parts[4])
                        the_invocation = webui.imanager.get_invocation(uid)
                        
                        solution = the_invocation.get_solutions()[sol_id]
                        test     = the_invocation.get_tests()[test_id]
                        the_test = webui.prob.get_testset().by_index(test)
                    except:
                        self.send_404()
                        return
                    
                    if the_invocation == None:
                        self.send_404()
                        return
                    
                    self.render("invocation_run.html", prob=webui.prob, uid=uid, solution=solution, sol_id=sol_id, invocation=the_invocation, test_id=test_id, test=test, the_test=the_test, **self.get_template_namespace())
                    return

                if len(parts) == 4 and parts[0] == "invocation" and parts[2] == "source" and webui.imanager != None:
                    the_invocation = None
                    uid      = None
                    sol_id   = None
                    solution = None
                    
                    try:
                        uid     = int(parts[1])
                        sol_id  = int(parts[3])
                        the_invocation = webui.imanager.get_invocation(uid)
                        
                        solution = the_invocation.get_solutions()[sol_id]
                    except:
                        self.send_404()
                        return
                    
                    if the_invocation == None:
                        self.send_404()
                        return

                    code = None
                    try:
                        with open(webui.prob.relative("solutions", solution), "r") as fp:
                            code = fp.read()
                    except:
                        self.send_404()
                        return

                    try:
                        import pygments, pygments.lexers, pygments.formatters, pygments.styles
                    except:
                        self.send_txt_data("To use syntax highlighting please install pygments!\n\n\n" + code)
                        return

                    try:
                        lexer     = pygments.lexers.get_lexer_by_name("c++")
                        style     = pygments.styles.get_style_by_name("igor")
                        formatter = pygments.formatters.get_formatter_by_name("html", style=style, full=True, linenos='table')
                        res = pygments.highlight(code, lexer, formatter)
                        self.send_txt_data(res, code=200)
                    except Exception as ex:
                        self.send_txt_data("There was error during highlighting", code=500)
                        print(ex)
                    return
                
                self.send_404()
        
        self.server  = http.server.HTTPServer(("localhost", self.port), WebHandler)
        self.server.server_version = "pmaker/" + pmaker.__version__

    def mode_testview(self):
        self.default = "/test_view"

    def mode_invocation_list(self, imanager):
        self.imanager = imanager
        self.default = "/invocation"
        
    def mode_invocation(self, uid, imanager):
        self.imanager = imanager
        self.default = "/invocation/{}".format(uid)
    
    def start(self):                
        print("Please connect to http://localhost:{}".format(self.port))
        self.server.serve_forever()
