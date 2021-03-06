#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017 F5 Networks Inc.
# GNU General Public License v3.0 (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'metadata_version': '1.1',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = r'''
---
module: bigip_irule
short_description: Manage iRules across different modules on a BIG-IP
description:
  - Manage iRules across different modules on a BIG-IP.
version_added: "2.2"
options:
  content:
    description:
      - When used instead of 'src', sets the contents of an iRule directly to
        the specified value. This is for simple values, but can be used with
        lookup plugins for anything complex or with formatting. Either one
        of C(src) or C(content) must be provided.
  module:
    description:
      - The BIG-IP module to add the iRule to.
    required: True
    choices:
      - ltm
      - gtm
  name:
    description:
      - The name of the iRule.
    required: True
  src:
    description:
      - The iRule file to interpret and upload to the BIG-IP. Either one
        of C(src) or C(content) must be provided.
    required: True
  state:
    description:
      - Whether the iRule should exist or not.
    default: present
    choices:
      - present
      - absent
  partition:
    description:
      - Device partition to manage resources on.
    default: Common
    version_added: 2.5
notes:
  - Requires the f5-sdk Python package on the host. This is as easy as
    pip install f5-sdk.
extends_documentation_fragment: f5
requirements:
  - f5-sdk
author:
  - Tim Rupp (@caphrim007)
'''

EXAMPLES = r'''
- name: Add the iRule contained in template irule.tcl to the LTM module
  bigip_irule:
    content: "{{ lookup('template', 'irule.tcl') }}"
    module: ltm
    name: MyiRule
    password: secret
    server: lb.mydomain.com
    state: present
    user: admin
  delegate_to: localhost

- name: Add the iRule contained in static file irule.tcl to the LTM module
  bigip_irule:
    module: ltm
    name: MyiRule
    password: secret
    server: lb.mydomain.com
    src: irule.tcl
    state: present
    user: admin
  delegate_to: localhost
'''

RETURN = r'''
module:
  description: The module that the iRule was added to
  returned: changed and success
  type: string
  sample: gtm
src:
  description: The filename that included the iRule source
  returned: changed and success, when provided
  type: string
  sample: /opt/src/irules/example1.tcl
content:
  description: The content of the iRule that was managed
  returned: changed and success
  type: string
  sample: "when LB_FAILED { set wipHost [LB::server addr] }"
'''

import os

from ansible.module_utils.f5_utils import AnsibleF5Client
from ansible.module_utils.f5_utils import AnsibleF5Parameters
from ansible.module_utils.f5_utils import HAS_F5SDK
from ansible.module_utils.f5_utils import F5ModuleError

try:
    from ansible.module_utils.f5_utils import iControlUnexpectedHTTPError
except ImportError:
    HAS_F5SDK = False


class Parameters(AnsibleF5Parameters):
    api_map = {
        'apiAnonymous': 'content'
    }

    updatables = [
        'content'
    ]

    api_attributes = [
        'apiAnonymous'
    ]

    returnables = [
        'content', 'src', 'module'
    ]

    def to_return(self):
        result = {}
        try:
            for returnable in self.returnables:
                result[returnable] = getattr(self, returnable)
            result = self._filter_params(result)
        except Exception:
            pass
        return result

    def api_params(self):
        result = {}
        for api_attribute in self.api_attributes:
            if self.api_map is not None and api_attribute in self.api_map:
                result[api_attribute] = getattr(self, self.api_map[api_attribute])
            else:
                result[api_attribute] = getattr(self, api_attribute)
        result = self._filter_params(result)
        return result

    @property
    def content(self):
        if self._values['content'] is None:
            result = self.src_content
        else:
            result = self._values['content']

        return str(result).strip()

    @property
    def src(self):
        if self._values['src'] is None:
            return None
        return self._values['src']

    @property
    def src_content(self):
        if not os.path.exists(self._values['src']):
            raise F5ModuleError(
                "The specified 'src' was not found."
            )
        with open(self._values['src']) as f:
            result = f.read()
        return result


class ModuleManager(object):
    def __init__(self, client):
        self.client = client

    def exec_module(self):
        if self.client.module.params['module'] == 'ltm':
            manager = self.get_manager('ltm')
        elif self.client.module.params['module'] == 'gtm':
            manager = self.get_manager('gtm')
        else:
            raise F5ModuleError(
                "An unknown iRule module type was specified"
            )
        return manager.exec_module()

    def get_manager(self, type):
        if type == 'ltm':
            return LtmManager(self.client)
        elif type == 'gtm':
            return GtmManager(self.client)


class BaseManager(object):
    def __init__(self, client):
        self.client = client
        self.want = Parameters(self.client.module.params)
        self.changes = Parameters()

    def exec_module(self):
        changed = False
        result = dict()
        state = self.want.state

        try:
            if state == "present":
                changed = self.present()
            elif state == "absent":
                changed = self.absent()
        except iControlUnexpectedHTTPError as e:
            raise F5ModuleError(str(e))

        changes = self.changes.to_return()
        result.update(**changes)
        result.update(dict(changed=changed))
        return result

    def _set_changed_options(self):
        changed = {}
        for key in Parameters.returnables:
            if getattr(self.want, key) is not None:
                changed[key] = getattr(self.want, key)
        if changed:
            self.changes = Parameters(changed)

    def _update_changed_options(self):
        changed = {}
        for key in Parameters.updatables:
            if getattr(self.want, key) is not None:
                attr1 = getattr(self.want, key)
                attr2 = getattr(self.have, key)
                if attr1 != attr2:
                    changed[key] = attr1
        if changed:
            self.changes = Parameters(changed)
            return True
        return False

    def present(self):
        if not self.want.content and not self.want.src:
            raise F5ModuleError(
                "Either 'content' or 'src' must be provided"
            )
        if self.exists():
            return self.update()
        else:
            return self.create()

    def create(self):
        self._set_changed_options()
        if self.client.check_mode:
            return True
        self.create_on_device()
        if not self.exists():
            raise F5ModuleError("Failed to create the iRule")
        return True

    def should_update(self):
        result = self._update_changed_options()
        if result:
            return True
        return False

    def update(self):
        self.have = self.read_current_from_device()
        if not self.should_update():
            return False
        if self.client.check_mode:
            return True
        self.update_on_device()
        return True

    def absent(self):
        if self.exists():
            return self.remove()
        return False

    def remove(self):
        if self.client.check_mode:
            return True
        self.remove_from_device()
        if self.exists():
            raise F5ModuleError("Failed to delete the iRule")
        return True


class LtmManager(BaseManager):
    def exists(self):
        result = self.client.api.tm.ltm.rules.rule.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.changes.api_params()
        resource = self.client.api.tm.ltm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        resource.update(**params)

    def create_on_device(self):
        params = self.want.api_params()
        resource = self.client.api.tm.ltm.rules.rule
        resource.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )

    def read_current_from_device(self):
        resource = self.client.api.tm.ltm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return Parameters(result)

    def remove_from_device(self):
        resource = self.client.api.tm.ltm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        resource.delete()


class GtmManager(BaseManager):
    def read_current_from_device(self):
        resource = self.client.api.tm.gtm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        result = resource.attrs
        return Parameters(result)

    def remove_from_device(self):
        resource = self.client.api.tm.gtm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        resource.delete()

    def exists(self):
        result = self.client.api.tm.gtm.rules.rule.exists(
            name=self.want.name,
            partition=self.want.partition
        )
        return result

    def update_on_device(self):
        params = self.changes.api_params()
        resource = self.client.api.tm.gtm.rules.rule.load(
            name=self.want.name,
            partition=self.want.partition
        )
        resource.update(**params)

    def create_on_device(self):
        params = self.want.api_params()
        resource = self.client.api.tm.gtm.rules.rule
        resource.create(
            name=self.want.name,
            partition=self.want.partition,
            **params
        )


class ArgumentSpec(object):
    def __init__(self):
        self.supports_check_mode = True
        self.argument_spec = dict(
            content=dict(
                required=False,
                default=None
            ),
            src=dict(
                required=False,
                default=None
            ),
            name=dict(required=True),
            module=dict(
                required=True,
                choices=['gtm', 'ltm']
            )
        )
        self.mutually_exclusive = [
            ['content', 'src']
        ]
        self.f5_product_name = 'bigip'


def cleanup_tokens(client):
    try:
        resource = client.api.shared.authz.tokens_s.token.load(
            name=client.api.icrs.token
        )
        resource.delete()
    except Exception:
        pass


def main():
    spec = ArgumentSpec()

    client = AnsibleF5Client(
        argument_spec=spec.argument_spec,
        supports_check_mode=spec.supports_check_mode,
        f5_product_name=spec.f5_product_name,
        mutually_exclusive=spec.mutually_exclusive,
    )

    try:
        if not HAS_F5SDK:
            raise F5ModuleError("The python f5-sdk module is required")

        mm = ModuleManager(client)
        results = mm.exec_module()
        cleanup_tokens(client)
        client.module.exit_json(**results)
    except F5ModuleError as e:
        cleanup_tokens(client)
        client.module.fail_json(msg=str(e))


if __name__ == '__main__':
    main()
