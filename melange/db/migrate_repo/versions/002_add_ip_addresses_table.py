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
from sqlalchemy.schema import (Column, MetaData, Table,ForeignKey)

from melange.db.migrate_repo.schema import (
    Boolean, DateTime, Integer, String, Text,
    create_tables, drop_tables, from_migration_import)


def define_ip_addresses_table(meta):
    (define_ip_blocks_table,) = from_migration_import(
        '001_add_ip_blocks_table', ['define_ip_blocks_table'])
    
    ip_blocks = define_ip_blocks_table(meta)


    ip_addresses = Table('ip_addresses', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        Column('address', String(255),nullable=False),
        Column('allocated',Boolean(),nullable=False),
        Column('port_id', String(255),nullable=True),
        Column('ip_block_id', Integer(),ForeignKey('ip_blocks.id'),nullable=True),
        Column('created_at', DateTime(), nullable=False),
        Column('updated_at', DateTime())
        )
    return ip_addresses

def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = [define_ip_addresses_table(meta)]
    create_tables(tables)

def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    tables = [define_ip_addresses_table(meta)]
    drop_tables(tables)