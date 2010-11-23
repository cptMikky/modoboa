# -*- coding: utf-8 -*-
import time
import sys
from django.http import HttpResponse, Http404
from django.template import Template, Context
from django.template.loader import render_to_string
from django.utils import simplejson
from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required
from modoboa.admin.models import Mailbox
from modoboa.lib import parameters, _render, _render_error, \
    getctx, is_not_localadmin, _render_to_string
from modoboa.lib.email_listing import parse_search_parameters
from lib import *
from forms import *
from templatetags.webextras import *

def __get_current_url(request):
    res = "%s?page=%s" % (request.session["folder"], request.session["page"])
    for p in ["criteria", "pattern", "order"]:
        if p in request.session.keys():
            res += "&%s=%s" % (p, request.session[p])
    return res

def __render_folders(mbc, request):
    return render_to_string("webmail/folders.html", {
            "selected" : request.session["folder"],
            "folders" : mbc.getfolders(request.user)
            })

@login_required
@is_not_localadmin()
def folder(request, name, updatenav=True):
    if not name:
        name = "INBOX"
    order = request.GET.has_key("order") and request.GET["order"] or "-date"
    if updatenav:
        pageid = request.GET.has_key("page") and int(request.GET["page"]) or 1
        if not "navparams" in request.session.keys():
            request.session["navparams"] = {}
        request.session["folder"] = name
        request.session["page"] = pageid
        if order:
            request.session["navparams"]["order"] = order
        parse_search_parameters(request)
    else:
        # Internal usage
        order = request.session["navparams"]["order"]

    optparams = {}
    if request.session.has_key("pattern"):
        optparams["pattern"] = request.session["pattern"]
        optparams["criteria"] = request.session["criteria"]
    else:
        optparams["reset"] = True
    optparams["elems_per_page"] = int(parameters.get_user(request.user, "MESSAGES_PER_PAGE"))
    lst = ImapListing(request.user, request.session["password"],
                      baseurl=name, folder=name, order=order, 
                      **optparams)

    page = lst.paginator.getpage(request.session["page"])
    dico = {"folders" : __render_folders(lst.mbc, request), 
            "menu" : listing_menu("", name, request.user)}
    if page:
        dico["listing"] = lst.fetch(request, page.id_start, page.id_stop)
        dico["navbar"] = lst.render_navbar(page)
    else:
        dico["listing"] = "<div class='info'>%s</div>" \
            % _("This folder contains no messages")
        dico["navbar"] = ""
    dico["quota"] = lst.getquota()

    ctx = getctx("ok", **dico)
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
@is_not_localadmin()
def index(request):
    #try:
    navp = request.session.has_key("navparams") \
        and request.session["navparams"] or {}
    lst = ImapListing(request.user, request.session["password"],
                      baseurl="INBOX", navparams=navp, folder="INBOX",
                      empty=True)
    #except Exception, exp:
    #    return _render_error(request, user_context={"error" : exp})
    return lst.render(request)

def fetchmail(request, folder, mail_id, all=False):
    res = IMAPconnector(user=request.user.username, 
                        password=request.session["password"]).fetch(start=mail_id, 
                                                                    folder=folder, 
                                                                    all=all)
    if len(res):
        return res[0]
    return None

@login_required
@is_not_localadmin()
def viewmail(request, folder, mail_id=None):
    from templatetags.webextras import viewm_menu

    content = Template("""
<iframe width="100%" frameBorder="0" src="{{ url }}" id="mailcontent"></iframe>
""").render(Context({"url" : reverse(getmailcontent, args=[folder, mail_id])}))
    menu = viewm_menu("", __get_current_url(request), folder, mail_id,
                      request.user.get_all_permissions())
    mbc = IMAPconnector(user=request.user.username, 
                        password=request.session["password"])
    ctx = getctx("ok", menu=menu, listing=content, 
                 folders=__render_folders(mbc, request))
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
@is_not_localadmin()
def getmailcontent(request, folder, mail_id):
    msg = fetchmail(request, folder, mail_id, True)
    if "class" in msg.keys() and msg["class"] == "unseen":
        IMAPconnector(user=request.user.username,
                      password=request.session["password"]).msg_read(folder, mail_id)
        email = ImapEmail(msg, request.user, links="1")
    try:
        pageid = request.session["page"]
    except KeyError:
        pageid = "1"
    return _render(request, "common/viewmail.html", {
            "headers" : email.render_headers(folder=folder, mail_id=mail_id), 
            "folder" : folder, "imapid" : mail_id, "mailbody" : email.body
            })

@login_required
@is_not_localadmin()
def getattachment(request, folder, mail_id):
    if request.GET.has_key("partnumber"):
        headers = {"Content-Type" : "text/plain",
                   "Content-Transfer-Encoding" : None}
        icon = IMAPconnector(user=request.user.username, 
                             password=request.session["password"])
        part = icon.fetchpart(mail_id, folder, request.GET["partnumber"])
        if part is not None:
            if part.get_content_maintype() == "message":
                payload = part.get_payload(0)
            else:
                payload = part.get_payload(decode=True)
            resp = HttpResponse(payload)
            for hdr, default in headers.iteritems():
                if not part.has_key(hdr):
                    if default is not None:
                        resp[hdr] = default
                    else:
                        continue
                resp[hdr] = re.sub("\s", "", part[hdr])
            # I would add this part into the previous loop if was able
            # to use functions as default values... but I'm a bit lazy
            # :p
            if part.has_key("Content-Disposition"):
                resp["Content-Disposition"] = \
                    re.sub("\s", "", part["Content-Disposition"])
            else:
                resp["Content-Disposition"] = \
                    "attachment; filename=%s" % request.GET["fname"]
            resp["Content-Length"] = len(payload)
            return resp
    raise Http404

@login_required
@is_not_localadmin()
def move(request):
    for arg in ["msgset", "to"]:
        if not request.GET.has_key(arg):
            return
    mbc = IMAPconnector(user=request.user.username, 
                        password=request.session["password"])
    mbc.move(request.GET["msgset"], request.session["folder"], request.GET["to"])
    return folder(request, request.session["folder"], False)

@login_required
@is_not_localadmin()
def delete(request, fdname, mail_id):
    mbc = IMAPconnector(user=request.user.username,
                        password=request.session["password"])
    mbc.move(mail_id, fdname, parameters.get_user(request.user, "TRASH_FOLDER"))
    ctx = getctx("ok", next=__get_current_url(request))
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
@is_not_localadmin()
def mark(request, name):
    if not request.GET.has_key("status") or not request.GET.has_key("ids"):
        return
    mbc = IMAPconnector(user=request.user.username,
                        password=request.session["password"])
    try:
        getattr(mbc, "msg_%s" % request.GET["status"])(name, request.GET["ids"])
    except AttributeError:
        pass
    return folder(request, name, False)

@login_required
@is_not_localadmin()
def empty(request, name):
    if name == parameters.get_user(request.user, "TRASH_FOLDER"):
        mbc = IMAPconnector(user=request.user.username,
                            password=request.session["password"])
        mbc.empty(name)
    return folder(request, name, False)

@login_required
@is_not_localadmin()
def compact(request, name):
    mbc = IMAPconnector(user=request.user.username,
                        password=request.session["password"])
    mbc.compact(name)
    return folder(request, name, False)

def render_compose(request, form, posturl, email=None, insert_signature=False):
    menu = compose_menu("", __get_current_url(request), 
                        request.user.get_all_permissions())
    editor = parameters.get_user(request.user, "EDITOR")
    if email is None:
        body = ""
        textheader = ""
    else:
        body = email.body
        textheader = email.textheader
    if insert_signature:
        signature = EmailSignature(request.user)
        body += str(signature)

    content = _render_to_string(request, "webmail/compose.html", {
            "form" : form, "bodyheader" : textheader,
            "body" : body, "posturl" : posturl
            })
    mbc = IMAPconnector(user=request.user.username, 
                        password=request.session["password"])
    ctx = getctx("ok", level=2, menu=menu, listing=content, 
                 folders=__render_folders(mbc, request),
                 editor=editor)
    return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

def __html2plaintext(content):
    """HTML to plain text translation

    :param content: some HTML content
    """
    html = lxml.html.fromstring(content)
    plaintext = ""
    for ch in html.iter():
        p = None
        if ch.text is not None:
            p = ch.text.strip('\r\t\n')
        if ch.tag == "img":
            p = ch.get("alt")
        if p is None:
            continue
        plaintext += p + "\n"
        
    return plaintext
    
def send_mail(request, withctx=False, origmsg=None, posturl=None):
    form = ComposeMailForm(request.POST)
    error = None
    ctx = None
    if form.is_valid():
        from email.mime.text import MIMEText
        from email.utils import make_msgid, formatdate
        import smtplib

        subtype = parameters.get_user(request.user, "EDITOR")
        body = request.POST["id_body"]
        charset = "utf-8"
        if subtype == "html":
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart(_subtype="related")
            submsg = MIMEMultipart(_subtype="alternative")
            textbody = __html2plaintext(body)
            submsg.attach(MIMEText(textbody.encode(charset),
                                _subtype="plain", _charset=charset))
            body, images = find_images_in_body(body)
            submsg.attach(MIMEText(body.encode(charset), _subtype=subtype, 
                                _charset=charset))
            msg.attach(submsg)
            for img in images:
                msg.attach(img)
        else:
            msg = MIMEText(body.encode(charset), _subtype=subtype)

        mb = Mailbox.objects.get(full_address=request.POST["from_"])
        msg["Subject"] = request.POST["subject"]
        if mb is None:
            msg["From"] = request.POST["from_"]
        else:
            msg["From"] = "%s <%s>" % (mb.name, request.POST["from_"])
        msg["To"] = request.POST["to"]
        msg["Message-ID"] = make_msgid()
        msg["User-Agent"] = "Modoboa"
        msg["Date"] = formatdate(time.time(), True)
        if origmsg and origmsg.has_key("Message-ID"):
            msg["References"] = msg["In-Reply-To"] = origmsg["Message-ID"]
        rcpts = msg['To'].split(',')
        if "cc" in request.POST.keys():
            msg["Cc"] = request.POST["cc"]
            rcpts += msg["Cc"].split(",")
        error = None
        try:
            s = smtplib.SMTP(parameters.get_admin("SMTP_SERVER"))
            if parameters.get_admin("SMTP_SECURED") == "yes":
                s.starttls()
        except (smtplib.SMTPException, ssl.SSLError), text:
            error = text
        if error is None:
            if parameters.get_admin("SMTP_AUTHENTICATION") == "yes":
                s.login(request.user.username, decrypt(request.session["password"]))
            s.sendmail(msg['From'], rcpts, msg.as_string())
            s.quit()
            sentfolder = parameters.get_user(request.user, "SENT_FOLDER")
            IMAPconnector(user=request.user.username,
                          password=request.session["password"]).push_mail(sentfolder, msg)
            ctx = getctx("ok", url=__get_current_url(request))

    if ctx is None:
        listing = render_to_string("webmail/compose.html", 
                                   {"form" : form, 
                                    "body" : request.POST["id_body"].strip(),
                                    "posturl" : posturl})
        ctx = getctx("ko", level=2, error=error, listing=listing)

    if not withctx:
        return HttpResponse(simplejson.dumps(ctx), mimetype="application/json")
    return ctx, HttpResponse(simplejson.dumps(ctx), mimetype="application/json")

@login_required
@is_not_localadmin()
def compose(request):
    if request.method == "POST":
        return send_mail(request, posturl=reverse(compose))

    form = ComposeMailForm()
    form.fields["from_"].initial = request.user.username
    return render_compose(request, form, reverse(compose), insert_signature=True)

@login_required
@is_not_localadmin()
def reply(request, folder, mail_id):
    msg = fetchmail(request, folder, mail_id, True)
    if request.method == "POST":
        ctx, r = send_mail(request, True, origmsg=msg, 
                           posturl=reverse(reply, args=[folder, mail_id]))
        if ctx["status"] == "ok":
            IMAPconnector(user=request.user.username,
                          password=request.session["password"]).msg_answered(folder,
                                                                             mail_id)
        return r

    form = ComposeMailForm()    
    email = ReplyModifier(msg, request.user, form, request.GET.has_key("full"),
                          addrfull=True, links="1")
    return render_compose(request, form, reverse(reply, args=[folder, mail_id]),
                          email)

@login_required
@is_not_localadmin()
def forward(request, folder, mail_id):
    if request.method == "POST":
        ctx, response = send_mail(request, True, 
                                  posturl=reverse(forward, args=[folder, mail_id]))
        if ctx["status"] == "ok":
            IMAPconnector(user=request.user.username,
                          password=request.session["password"]).msgforwarded(folder,
                                                                             mail_id)
        return response
    
    msg = fetchmail(request, folder, mail_id, True)
    form = ComposeMailForm()
    email = ForwardModifier(msg, request.user, form, addrfull=True, links="1")
    return render_compose(request, form, reverse(forward, args=[folder, mail_id]), 
                          email)