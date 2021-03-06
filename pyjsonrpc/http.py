#!/usr/bin/env python
# coding: utf-8

import sys
import urllib2
import base64
import BaseHTTPServer
import SocketServer
import httplib
import urllib
import urlparse
import rpcrequest
import rpcresponse
import rpcerror
import rpclib
import Cookie
from rpcjson import json

import httplib
import gzip
import StringIO



def http_request(
    url,
    json_string,
    username = None,
    password = None,
    timeout = None,
    additional_headers = None,
    content_type = None,
    cookies = None,
    gzipped = False
):
    """
    Fetch data from webserver (POST request)

    :param json_string: JSON-String

    :param username: If *username* is given, BASE authentication will be used.

    :param timeout: Specifies a timeout in seconds for blocking operations
        like the connection attempt (if not specified, the global default
        timeout setting will be used).
        See: https://github.com/gerold-penz/python-jsonrpc/pull/6

    :param additional_headers: Dictionary with additional headers
        See: https://github.com/gerold-penz/python-jsonrpc/issues/5

    :param content_type: Possibility to change the content-type header.

    :param cookies: Possibility to add simple cookie-items as key-value pairs.
        The key and the value of each cookie-item must be a bytestring.
        Unicode is not allowed here.
    """

    request = urllib2.Request(url)

    if gzipped:
        jh = StringIO.StringIO()
        gz = gzip.GzipFile(fileobj=jh, mode='wb')
        gz.write(json_string)
        gz.close()
        json_string = jh.getvalue()
        jh.close()

        request.add_header('content-encoding', 'gzip')
        request.add_header('Accept-Encoding', 'gzip')

    request.add_data(json_string)

    request.add_header("Content-Type", "application/json")
    if username:
        base64string = base64.encodestring("%s:%s" % (username, password))[:-1]
        request.add_header("Authorization", "Basic %s" % base64string)



    # handler=urllib2.HTTPHandler(debuglevel=1)
    # opener = urllib2.build_opener(handler)
    # urllib2.install_opener(opener)

    # Cookies
    if cookies:
        cookie = Cookie.SimpleCookie(cookies)
        request.add_header("Cookie", cookie.output(header = "", sep = ";"))

    # Additional headers (overrides other headers)
    if additional_headers:
        for key, val in additional_headers.items():
            request.add_header(key, val)

    # Request
    response = urllib2.urlopen(request, timeout = timeout)

    response_string = response.read()

    if 'Content-Encoding' in response.headers:
        if response.headers['Content-Encoding'] == 'gzip':
            rh = StringIO.StringIO(response_string)
            rz = gzip.GzipFile(fileobj=rh, mode='rb')
            response_string = rz.read()
            rz.close()
            rh.close()

    response.close()

    # Finished
    return response_string


class HttpClient(object):
    class _Method(object):

        def __init__(self, http_client_instance, method):
            self.http_client_instance = http_client_instance
            self.method = method

        def __call__(self, *args, **kwargs):
            return self.http_client_instance.call(self.method, *args, **kwargs)

    def __init__(
        self,
        url,
        username = None,
        password = None,
        gzipped = False,
        timeout = None,
        additional_headers = None,
        content_type = None,
        cookies = None
    ):
        """
        :param: URL to the JSON-RPC handler on the HTTP-Server.
            Example: ``"https://example.com/jsonrpc"``

        :param username: If *username* is given, BASE authentication will be used.
        :param password: Password for BASE authentication.
        :param gzipped: Compress requests.
        :param timeout:


        """

        self.url = url
        self.username = username
        self.password = password
        self.gzip_requests = gzipped
        self.timeout = timeout
        self.additional_headers = additional_headers
        self.content_type = content_type
        self.cookies = cookies

    def call(self, method, *args, **kwargs):
        """
        Creates the JSON-RPC request string, calls the HTTP server, converts
        JSON-RPC response string to python and returns the result.

        :param method: Name of the method which will be called on the HTTP server.
            Or a list with RPC-Request-Dictionaries. Syntax::

                "<MethodName>" or [<JsonRpcRequestDict>, ...]

            RPC-Request-Dictionaries will be made with the function
            *rpcrequest.create_request_dict()*.
        """

        # Create JSON-RPC-request
        if isinstance(method, basestring):
            request_json = rpcrequest.create_request_json(method, *args, **kwargs)
        else:
            assert not args and not kwargs
            request_json = json.dumps(method)

        # Call the HTTP-JSON-RPC server
        response_json = http_request(
            url = self.url,
            json_string = request_json,
            username = self.username,
            password = self.password,
            gzipped=self.gzip_requests,
            timeout = self.timeout,
            additional_headers = self.additional_headers,
            content_type = self.content_type,
            cookies = self.cookies

        )
        if not response_json:
            return

        # Convert JSON-RPC-response to python-object
        response = rpcresponse.parse_response_json(response_json)
        if isinstance(response, rpcresponse.Response):
            if response.error:
                # Raise error
                if response.error.code in rpcerror.jsonrpcerrors:
                    raise rpcerror.jsonrpcerrors[response.error.code](
                        message = response.error.message,
                        data = response.error.data
                    )
                else:
                    raise rpcerror.JSONApplicationError(
                        code=response.error.code,
                        message=response.error.message,
                        data=response.error.data
                    )
            else:
                # Return result
                return response.result
        elif isinstance(response, list):
            # Bei Listen wird keine Fehlerauswerung gemacht
            return response

    def notify(self, method, *args, **kwargs):
        """
        Sends a notification or multiple notifications to the server.

        A notification is a special request which does not have a response.
        """

        methods = []

        # Create JSON-RPC-request
        if isinstance(method, basestring):
            request_dict = rpcrequest.create_request_dict(method, *args, **kwargs)
            request_dict["id"] = None
            methods.append(request_dict)
        else:
            assert not args and not kwargs
            for request_dict in method:
                request_dict["id"] = None
                methods.append(request_dict)

        # Redirect to call-method
        self.call(methods)

        # Fertig
        return

    # for compatibility with jsonrpclib
    _notify = notify


    def __call__(self, method, *args, **kwargs):
        """
        Redirects the direct call to *self.call*
        """

        return self.call(method, *args, **kwargs)


    def __getattr__(self, method):
        """
        Allows the usage of attributes as *method* names.
        """

        return self._Method(http_client_instance = self, method = method)


class ThreadingHttpServer(SocketServer.ThreadingMixIn, BaseHTTPServer.HTTPServer):
    """
    Threading HTTP Server
    """
    pass


class HttpRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler, rpclib.JsonRpc):
    """
    HttpRequestHandler for JSON-RPC-Requests

    Info: http://www.simple-is-better.org/json-rpc/transport_http.html
    """

    protocol_version = "HTTP/1.1"
    content_type = "application/json"


    def set_content_type(self, content_type):
        """
        Set content-type to *content_type*
        """

        self.send_header("Content-Type", content_type)


    def set_content_type_json(self):
        """
        Set content-type to "application/json"
        """

        self.set_content_type("application/json")


    def set_no_cache(self):
        """
        Disable caching
        """

        self.send_header("Cache-Control", "no-cache")
        self.send_header("Pragma", "no-cache")


    def set_content_length(self, length):
        """
        Set content-length-header
        """

        self.send_header("Content-Length", str(length))


    def do_GET(self):
        """
        Handles HTTP-GET-Request
        """

        # Parse URL query
        path, query_str = urllib.splitquery(self.path)
        if not query_str:
            # Bad Request
            return self.send_error(httplib.BAD_REQUEST)

        # Parse querystring
        query = urlparse.parse_qs(query_str)

        # jsonrpc
        jsonrpc = query.get("jsonrpc")
        if jsonrpc:
            jsonrpc = jsonrpc[0]

        # id
        id = query.get("id")
        if id:
            id = id[0]

        # method
        method = query.get("method")
        if method:
            method = method[0]
        else:
            # Bad Request
            return self.send_error(httplib.BAD_REQUEST)

        # params
        args = []
        kwargs = {}
        params = query.get("params")
        if params:
            params = json.loads(params[0])
            if isinstance(params, list):
                args = params
                kwargs = {}
            elif isinstance(params, dict):
                args = []
                kwargs = params

        # Create JSON reqeust string
        request_dict = rpcrequest.create_request_dict(method, *args, **kwargs)
        request_dict["jsonrpc"] = jsonrpc
        request_dict["id"] = id
        request_json = json.dumps(request_dict)

        # Call
        response_json = self.call(request_json) or ""

        # Return result
        self.send_response(code = httplib.OK)
        self.set_content_type(self.content_type)
        self.set_no_cache()
        self.set_content_length(len(response_json))
        self.end_headers()
        self.wfile.write(response_json)


    def do_POST(self):
        """
        Handles HTTP-POST-Request
        """

        # Read JSON request
        content_length = int(self.headers.get("Content-Length", 0))
        request_json = self.rfile.read(content_length)

        # Call
        response_json = self.call(request_json) or ""

        # Return result
        self.send_response(code = httplib.OK)
        self.set_content_type(self.content_type)
        self.set_no_cache()
        self.set_content_length(len(response_json))
        self.end_headers()
        self.wfile.write(response_json)
        return


def handle_cgi_request(methods = None):
    """
    Gets the JSON-RPC request from CGI environment and returns the
    result to STDOUT
    """

    import cgi
    import cgitb
    cgitb.enable()

    # get response-body
    request_json = sys.stdin.read()
    if request_json:
        # POST
        request_json = urlparse.unquote(request_json)
    else:
        # GET
        args = []
        kwargs = {}
        fields = cgi.FieldStorage()
        jsonrpc = fields.getfirst("jsonrpc")
        id = fields.getfirst("id")
        method = fields.getfirst("method")
        params = fields.getfirst("params")
        if params:
            params = json.loads(params)
            if isinstance(params, list):
                args = params
                kwargs = {}
            elif isinstance(params, dict):
                args = []
                kwargs = params

        # Create JSON request string
        request_dict = rpcrequest.create_request_dict(method, *args, **kwargs)
        request_dict["jsonrpc"] = jsonrpc
        request_dict["id"] = id
        request_json = json.dumps(request_dict)

    # Call
    response_json = rpclib.JsonRpc(methods = methods).call(request_json)

    # Return headers
    print "Content-Type: application/json"
    print "Cache-Control: no-cache"
    print "Pragma: no-cache"
    print

    # Return result
    print response_json

