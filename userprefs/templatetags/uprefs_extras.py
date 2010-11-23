from django import template
from django.template.loader import render_to_string
from django.utils.translation import ugettext as _
from django.core.urlresolvers import reverse
from modoboa import userprefs
from modoboa.lib import events

register = template.Library()

@register.simple_tag
def options_menu(user):
    entries = [
        {"name"  : "userprefs",
         "img"   : "/static/pics/user.png",
         "label" : _("Options"),
         "class" : "topdropdown",
         "menu"  : [
                {"name" : "changepwd",
                 "url" : reverse(userprefs.views.changepassword),
                 "img" : "/static/pics/edit.png",
                 "label" : _("Change password"),
                 "class" : "boxed",
                 "rel" : "{handler:'iframe',size:{x:350,y:220}}"},
                {"name" : "preferences",
                 "img" : "/static/pics/user.png",
                 "label" : _("Preferences"),
                 "url" : reverse(userprefs.views.preferences),
                 }
                ]
         },
        ]
    entries[0]["menu"] += events.raiseQueryEvent("UserMenuDisplay", 
                                                 target="options_menu")

    return render_to_string('common/menulist.html', 
                            {"entries" : entries, "user" : user})

@register.simple_tag
def uprefs_menu(user):
    entries = []
    entries += events.raiseQueryEvent("UserMenuDisplay", 
                                      target="uprefs_menu")

    return render_to_string('common/menulist.html', 
                            {"entries" : entries, "user" : user})

@register.simple_tag
def loadextmenu(user):
    menu = events.raiseQueryEvent("UserMenuDisplay", target="top_menu", 
                                  user=user)
    return render_to_string('common/menulist.html', 
                            {"entries" : menu, "user" : user})