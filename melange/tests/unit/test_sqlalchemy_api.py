# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from melange.db.sqlalchemy import api as db_api
from melange.db.sqlalchemy import session
from melange.ipam import models
from melange import tests
from melange.tests import factories


class TestSqlalchemyApi(tests.BaseTest):

    def test_delete_does_soft_deletion(self):
        model = factories.models.IpBlockFactory()

        db_api.delete(model)

        deleted_model = session.raw_query(models.IpBlock).get(model.id)
        self.assertIsNotNone(deleted_model)
        self.assertTrue(deleted_model.deleted)

    def test_delete_all_does_soft_deletion(self):
        model1 = factories.models.IpBlockFactory()
        model2 = factories.models.IpBlockFactory()

        db_api.delete_all(models.IpBlock)

        for model in [model1, model2]:
            deleted_model = session.raw_query(models.IpBlock).get(model.id)
            self.assertIsNotNone(deleted_model)
            self.assertTrue(deleted_model.deleted)