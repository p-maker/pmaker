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
                return {"shortly": WebHandler.get_file_preview, "escape": html.escape}
                
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

                    
                    
                self.send_404()
        
        self.server  = http.server.HTTPServer(("localhost", self.port), WebHandler)
        self.server.server_version = "pmaker/" + pmaker.__version__

    def mode_testview(self):
        self.default = "/test_view"

    def mode_invokation_list(self):
        self.default = "/invokation"
        
    def mode_invokation(self, invokation_id):
        self.default = "/invokation/{}".format(invokation_id)
    
    def start(self):                
        print("Please connect to http://localhost:{}".format(self.port))
        self.server.serve_forever()
