# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from nextgisweb.component import Component, require
from nextgisweb.lib.config import Option

from .model import Base
from .util import COMP_ID


class PkkComponent(Component):
    identity = COMP_ID
    metadata = Base.metadata

    @require('resource')
    def setup_pyramid(self, config):
        from . import view, api
        view.setup_pyramid(self, config)
        api.setup_pyramid(self, config)

    option_annotations = (
        Option('host', str, default='http://127.0.0.1:8000',
               doc="aiorosreestr host address"),
        Option('timeout', float, default=10.0,
               doc="Timeout")
    )


def pkginfo():
    return dict(components=dict(
        pkk='nextgisweb_pkk'))


def amd_packages():
    return (
        ('ngw-pkk', 'nextgisweb_pkk:amd/ngw-pkk'),
    )
