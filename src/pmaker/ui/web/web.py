import http.server
import html
import jinja2

import pkg_resources

import pmaker
from pmaker.enter import NotUpdatedError

class WebUI:
    def __init__(self, prob):
        self.port = 8128
        self.prob = prob
        self.default = "/dashboard"
        self.template_cache = dict()
        self.imanager = None
        
        webui = self
        
        class WebHandler(http.server.BaseHTTPRequestHandler):
            def write_string(self, s):
                self.wfile.write(bytes(s, "utf-8"))

            def get_file_preview(path, limit=1024, linelimit=10):
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
                    
                        pre  = "<span class=\"data_text\">"
                        post = "<span class=\"data_text\">"
                        return pre + html.escape(s).replace("\n","<br>") + post
                except:
                    (_, ex, _) = sys.exc_info()
                    return "<span style=\"data_error\">failed to read: {}</span>".format(ex)

            def get_template_namespace(self):
                import builtins
                mp = builtins.__dict__
                mp["shortly"] = WebHandler.get_file_preview
                mp["escape"]  = html.escape
                
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
                self.wfile.write(data)

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
                    tests = None
                    
                    try:
                        tests = webui.prob.get_tests(noupdate=True)
                    except NotUpdatedError:
                        pass
                    
                    self.render("test_view.html", prob=webui.prob, tests=tests, **self.get_template_namespace())
                    return

                if parts[:2] == ["test_view", "show_test"] and len(parts) == 4 and parts[3] in ["input", "output"]:
                    try:
                        test = webui.prob.get_test_by_index(int(parts[2]))
                        if not test:
                            raise ValueError()

                        self.render("test_verbose.html", prob=webui.prob, test=test, part=parts[3], **self.get_template_namespace())
                        return
                    except ValueError:
                        self.send_404()
                        return

                if parts == ["invokation"] and webui.imanager != None:
                    invokations = webui.imanager.list_invokations()
                    active      = webui.imanager.list_active()

                    def is_active(name):
                        return name in active

                    def get_solutions(invokation):
                        try:
                            return " ".join(invokation.get_solutions())
                        except:
                            return "<span style='color: red'>Data not available</span>"

                    invokations.sort()
                    invokations.reverse()
                    self.render("invokation_list.html", prob=webui.prob, get_solutions=get_solutions, invokations=invokations, active=is_active, imanager=webui.imanager)
                    return
                    
                if parts[:1] == ["invokation"] and len(parts) == 2 and webui.imanager != None:
                    the_invokation = None
                    try:
                        the_invokation = webui.imanager.get_invokation(int(parts[1]))
                    except:
                        raise
                        #self.send_404()
                        #return
                    
                    if the_invokation == None:
                        self.send_404()
                        return
                    
                    solutions     = the_invokation.get_solutions()
                    test_indices  = the_invokation.get_tests()

                    def render_extras(i, j, hard_tl=False, tl_plus=False):
                        if the_invokation.get_descriptor(i, j).is_final():
                            (tm, mem) = the_invokation.get_descriptor(i, j).get_rusage()
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
                            return '<span class="invokation_stat">(%s, %s)</span>' % (display_tm, display_mem)
                        return ""

                    def render_cell(i, j):
                        hard_tl = False
                        tl_plus   = False

                        from pmaker.invokation import InvokationStatus
                        res = the_invokation.get_result(i, j)
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
                            internal = '<span class="iverdict iverdict_long">{}</span>'.format(res.name)
                        else:
                            internal = '<span class="iverdict">{}</span>'.format(res.name)
                        extras = ""
                        if res != InvokationStatus.INCOMPLETE:
                            extras   = render_extras(i, j, hard_tl=hard_tl, tl_plus=tl_plus)
                        return '<td class="invokation_cell_{}">{} {}</td>'.format(res.name, internal, extras)
                    
                    self.render("invokation.html", prob=webui.prob, invokation=the_invokation, solutions=solutions, test_indices=test_indices, render_cell=render_cell, **self.get_template_namespace())
                    return
                
                self.send_404()
        
        self.server  = http.server.HTTPServer(("localhost", self.port), WebHandler)
        self.server.server_version = "pmaker/" + pmaker.__version__

    def mode_testview(self):
        self.default = "/test_view"

    def mode_invokation_list(self, imanager):
        self.imanager = imanager
        self.default = "/invokation"
        
    def mode_invokation(self, uid, imanager):
        self.imanager = imanager
        self.default = "/invokation/{}".format(uid)
    
    def start(self):                
        print("Please connect to http://localhost:{}".format(self.port))
        self.server.serve_forever()
