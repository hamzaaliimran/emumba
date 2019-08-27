# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
"""
BitBake 'Fetch' clearcase implementation

The clearcase fetcher is used to retrieve files from a ClearCase repository.

Usage in the recipe:

    SRC_URI = "ccrc://cc.example.org/ccrc;vob=/example_vob;module=/example_module"
    SRCREV = "EXAMPLE_CLEARCASE_TAG"
    PV = "${@d.getVar("SRCREV", False).replace("/", "+")}"

The fetcher uses the rcleartool or cleartool remote client, depending on which one is available.

Supported SRC_URI options are:

- vob
    (required) The name of the clearcase VOB (with prepending "/")

- module
    The module in the selected VOB (with prepending "/")

    The module and vob parameters are combined to create
    the following load rule in the view config spec:
                load <vob><module>

- proto
    http or https

Related variables:

    CCASE_CUSTOM_CONFIG_SPEC
            Write a config spec to this variable in your recipe to use it instead
            of the default config spec generated by this fetcher.
            Please note that the SRCREV loses its functionality if you specify
            this variable. SRCREV is still used to label the archive after a fetch,
            but it doesn't define what's fetched.

User credentials:
    cleartool:
            The login of cleartool is handled by the system. No special steps needed.

    rcleartool:
            In order to use rcleartool with authenticated users an `rcleartool login` is
            necessary before using the fetcher.
"""
# Copyright (C) 2014 Siemens AG
#
# SPDX-License-Identifier: GPL-2.0-only
#

import os
import sys
import shutil
import bb
from   bb.fetch2 import FetchMethod
from   bb.fetch2 import FetchError
from   bb.fetch2 import runfetchcmd
from   bb.fetch2 import logger

class ClearCase(FetchMethod):
    """Class to fetch urls via 'clearcase'"""
    def init(self, d):
        pass

    def supports(self, ud, d):
        """
        Check to see if a given url can be fetched with Clearcase.
        """
        return ud.type in ['ccrc']

    def debug(self, msg):
        logger.debug(1, "ClearCase: %s", msg)

    def urldata_init(self, ud, d):
        """
        init ClearCase specific variable within url data
        """
        ud.proto = "https"
        if 'protocol' in ud.parm:
            ud.proto = ud.parm['protocol']
        if not ud.proto in ('http', 'https'):
            raise fetch2.ParameterError("Invalid protocol type", ud.url)

        ud.vob = ''
        if 'vob' in ud.parm:
            ud.vob = ud.parm['vob']
        else:
            msg = ud.url+": vob must be defined so the fetcher knows what to get."
            raise MissingParameterError('vob', msg)

        if 'module' in ud.parm:
            ud.module = ud.parm['module']
        else:
            ud.module = ""

        ud.basecmd = d.getVar("FETCHCMD_ccrc") or "/usr/bin/env cleartool || rcleartool"

        if d.getVar("SRCREV") == "INVALID":
          raise FetchError("Set a valid SRCREV for the clearcase fetcher in your recipe, e.g. SRCREV = \"/main/LATEST\" or any other label of your choice.")

        ud.label = d.getVar("SRCREV", False)
        ud.customspec = d.getVar("CCASE_CUSTOM_CONFIG_SPEC")

        ud.server     = "%s://%s%s" % (ud.proto, ud.host, ud.path)

        ud.identifier = "clearcase-%s%s-%s" % ( ud.vob.replace("/", ""),
                                                ud.module.replace("/", "."),
                                                ud.label.replace("/", "."))

        ud.viewname         = "%s-view%s" % (ud.identifier, d.getVar("DATETIME", d, True))
        ud.csname           = "%s-config-spec" % (ud.identifier)
        ud.ccasedir         = os.path.join(d.getVar("DL_DIR"), ud.type)
        ud.viewdir          = os.path.join(ud.ccasedir, ud.viewname)
        ud.configspecfile   = os.path.join(ud.ccasedir, ud.csname)
        ud.localfile        = "%s.tar.gz" % (ud.identifier)

        self.debug("host            = %s" % ud.host)
        self.debug("path            = %s" % ud.path)
        self.debug("server          = %s" % ud.server)
        self.debug("proto           = %s" % ud.proto)
        self.debug("type            = %s" % ud.type)
        self.debug("vob             = %s" % ud.vob)
        self.debug("module          = %s" % ud.module)
        self.debug("basecmd         = %s" % ud.basecmd)
        self.debug("label           = %s" % ud.label)
        self.debug("ccasedir        = %s" % ud.ccasedir)
        self.debug("viewdir         = %s" % ud.viewdir)
        self.debug("viewname        = %s" % ud.viewname)
        self.debug("configspecfile  = %s" % ud.configspecfile)
        self.debug("localfile       = %s" % ud.localfile)

        ud.localfile = os.path.join(d.getVar("DL_DIR"), ud.localfile)

    def _build_ccase_command(self, ud, command):
        """
        Build up a commandline based on ud
        command is: mkview, setcs, rmview
        """
        options = []

        if "rcleartool" in ud.basecmd:
            options.append("-server %s" % ud.server)

        basecmd = "%s %s" % (ud.basecmd, command)

        if command is 'mkview':
            if not "rcleartool" in ud.basecmd:
                # Cleartool needs a -snapshot view
                options.append("-snapshot")
            options.append("-tag %s" % ud.viewname)
            options.append(ud.viewdir)

        elif command is 'rmview':
            options.append("-force")
            options.append("%s" % ud.viewdir)

        elif command is 'setcs':
            options.append("-overwrite")
            options.append(ud.configspecfile)

        else:
            raise FetchError("Invalid ccase command %s" % command)

        ccasecmd = "%s %s" % (basecmd, " ".join(options))
        self.debug("ccasecmd = %s" % ccasecmd)
        return ccasecmd

    def _write_configspec(self, ud, d):
        """
        Create config spec file (ud.configspecfile) for ccase view
        """
        config_spec = ""
        custom_config_spec = d.getVar("CCASE_CUSTOM_CONFIG_SPEC", d)
        if custom_config_spec is not None:
            for line in custom_config_spec.split("\\n"):
                config_spec += line+"\n"
            bb.warn("A custom config spec has been set, SRCREV is only relevant for the tarball name.")
        else:
            config_spec += "element * CHECKEDOUT\n"
            config_spec += "element * %s\n" % ud.label
            config_spec += "load %s%s\n" % (ud.vob, ud.module)

        logger.info("Using config spec: \n%s" % config_spec)

        with open(ud.configspecfile, 'w') as f:
            f.write(config_spec)

    def _remove_view(self, ud, d):
        if os.path.exists(ud.viewdir):
            cmd = self._build_ccase_command(ud, 'rmview');
            logger.info("cleaning up [VOB=%s label=%s view=%s]", ud.vob, ud.label, ud.viewname)
            bb.fetch2.check_network_access(d, cmd, ud.url)
            output = runfetchcmd(cmd, d, workdir=ud.ccasedir)
            logger.info("rmview output: %s", output)

    def need_update(self, ud, d):
        if ("LATEST" in ud.label) or (ud.customspec and "LATEST" in ud.customspec):
            ud.identifier += "-%s" % d.getVar("DATETIME",d, True)
            return True
        if os.path.exists(ud.localpath):
            return False
        return True

    def supports_srcrev(self):
        return True

    def sortable_revision(self, ud, d, name):
        return False, ud.identifier

    def download(self, ud, d):
        """Fetch url"""

        # Make a fresh view
        bb.utils.mkdirhier(ud.ccasedir)
        self._write_configspec(ud, d)
        cmd = self._build_ccase_command(ud, 'mkview')
        logger.info("creating view [VOB=%s label=%s view=%s]", ud.vob, ud.label, ud.viewname)
        bb.fetch2.check_network_access(d, cmd, ud.url)
        try:
            runfetchcmd(cmd, d)
        except FetchError as e:
            if "CRCLI2008E" in e.msg:
                raise FetchError("%s\n%s\n" % (e.msg, "Call `rcleartool login` in your console to authenticate to the clearcase server before running bitbake."))
            else:
                raise e

        # Set configspec: Setting the configspec effectively fetches the files as defined in the configspec
        cmd = self._build_ccase_command(ud, 'setcs');
        logger.info("fetching data [VOB=%s label=%s view=%s]", ud.vob, ud.label, ud.viewname)
        bb.fetch2.check_network_access(d, cmd, ud.url)
        output = runfetchcmd(cmd, d, workdir=ud.viewdir)
        logger.info("%s", output)

        # Copy the configspec to the viewdir so we have it in our source tarball later
        shutil.copyfile(ud.configspecfile, os.path.join(ud.viewdir, ud.csname))

        # Clean clearcase meta-data before tar

        runfetchcmd('tar -czf "%s" .' % (ud.localpath), d, cleanup = [ud.localpath])

        # Clean up so we can create a new view next time
        self.clean(ud, d);

    def clean(self, ud, d):
        self._remove_view(ud, d)
        bb.utils.remove(ud.configspecfile)
