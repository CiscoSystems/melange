# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http: //www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
SQLAlchemy models for Melange data
"""
import netaddr
from netaddr.strategy.ipv6 import ipv6_verbose
from netaddr import IPNetwork, IPAddress

from datetime import timedelta
from melange.common.exception import MelangeError
from melange.db import api as db_api
from melange.common import utils
from melange.common.utils import cached_property, find, exclude
from melange.common.config import Config
from melange.common import data_types


class Query(object):

    def __init__(self, model, **conditions):
        self._model = model
        self._conditions = conditions

    def all(self):
        return db_api.find_all_by(self._model, **self._conditions)

    def __iter__(self):
        return iter(self.all())

    def update(self, **values):
        db_api.update_all(self._model, self._conditions, values)

    def delete(self):
        db_api.delete_all(self._model, **self._conditions)

    def limit(self, limit=200, marker=None, marker_column=None):
        return db_api.find_all_by_limit(self._model, self._conditions,
                                        limit=limit, marker=marker,
                                        marker_column=marker_column)


class ModelBase(object):
    _columns = {}
    _auto_generated_attrs = ["id", "created_at", "updated_at"]
    _data_fields = []

    @classmethod
    def create(cls, **values):
        values['id'] = utils.guid()
        values['created_at'] = utils.utcnow()
        instance = cls(**values)
        return instance.save()

    def save(self):
        if not self.is_valid():
            raise InvalidModelError(self.errors)
        self._convert_columns_to_proper_type()
        self._before_save()
        self['updated_at'] = utils.utcnow()
        return db_api.save(self)

    def delete(self):
        db_api.delete(self)

    def __init__(self, **kwargs):
        self.merge_attributes(kwargs)

    def _validate_columns_type(self):
        for column_name, column_type in self._columns.iteritems():
            try:
                column_type(self[column_name])
            except (TypeError, ValueError):
                self._add_error(column_name,
                       "{0} should be of type {1}".format(
                        column_name, column_type.__name__))

    def _validate(self):
        pass

    def _before_validate(self):
        pass

    def _before_save(self):
        pass

    def _convert_columns_to_proper_type(self):
        for column_name, column_type in self._columns.iteritems():
            self[column_name] = column_type(self[column_name])

    def is_valid(self):
        self.errors = {}
        self._validate_columns_type()
        self._before_validate()
        self._validate()
        return self.errors == {}

    def _validate_presence_of(self, attribute_name):
        if (self[attribute_name] in [None, ""]):
            self._add_error(attribute_name,
                            "{0} should be present".format(attribute_name))

    def _validate_existence_of(self, attribute, model_class, **conditions):
        model_id = self[attribute]
        conditions['id'] = model_id
        if model_id is not None and model_class.get_by(**conditions) is None:
            conditions_str = ", ".join(["{0} = {1}".format(key, repr(value))
                                     for key, value in conditions.iteritems()])
            self._add_error(attribute, "{0} with {1} doesn't "
                          "exist".format(model_class.__name__, conditions_str))

    @classmethod
    def find(cls, id):
        return cls.find_by(id=id)

    @classmethod
    def get(cls, id):
        return cls.get_by(id=id)

    @classmethod
    def find_by(cls, **conditions):
        model = cls.get_by(**conditions)
        if model == None:
            raise ModelNotFoundError("%s Not Found" % cls.__name__)
        return model

    @classmethod
    def get_by(cls, **kwargs):
        return db_api.find_by(cls, **cls._get_conditions(kwargs))

    @classmethod
    def _get_conditions(cls, raw_conditions):
        return raw_conditions

    @classmethod
    def find_all(cls, **kwargs):
        return Query(cls, **cls._get_conditions(kwargs))

    def merge_attributes(self, values):
        """dict.update() behaviour."""
        for k, v in values.iteritems():
            self[k] = v

    def update(self, **values):
        attrs = exclude(values, *self._auto_generated_attrs)
        self.merge_attributes(attrs)
        return self.save()

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        self._i = iter(db_api.columns_of(self))
        return self

    def __eq__(self, other):
        if not hasattr(other, 'id'):
            return False
        return type(other) == type(self) and other.id == self.id

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return id.__hash__()

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def to_dict(self):
        return self.__dict__()

    def data(self):
        data_fields = self._data_fields + self._auto_generated_attrs
        return dict([(field, self[field])
                    for field in data_fields])

    def _validate_positive_integer(self, attribute_name):
        if(utils.parse_int(self[attribute_name]) < 0):
            self._add_error(attribute_name,
                            "{0} should be a positive "
                            "integer".format(attribute_name))

    def _add_error(self, attribute_name, error_message):
        self.errors[attribute_name] = self.errors.get(attribute_name, [])
        self.errors[attribute_name].append(error_message)

    def _has_error_on(self, attribute):
        return self.errors.get(attribute, None) is not None


def ipv6_address_generator_factory(cidr, **kwargs):
    default_generator = "melange.ipv6.tenant_based_generator."\
                        "TenantBasedIpV6Generator"
    ip_generator_class_name = Config.get("ipv6_generator", default_generator)
    ip_generator = utils.import_class(ip_generator_class_name)
    required_params = ip_generator.required_params\
        if hasattr(ip_generator, "required_params") else []
    missing_params = set(required_params) - set(kwargs.keys())
    if missing_params:
        raise DataMissingError("Required params are missing: {0}".\
                                   format(', '.join(missing_params)))
    return ip_generator(cidr, **kwargs)


class IpAddressIterator(object):

    def __init__(self, generator):
        self.generator = generator

    def __iter__(self):
        return self

    def next(self):
        return self.generator.next_ip()


class IpBlock(ModelBase):

    _allowed_types = ["private", "public"]
    _data_fields = ['cidr', 'network_id', 'policy_id', 'tenant_id',
                    'parent_id', 'type']

    @classmethod
    def find_or_allocate_ip(cls, ip_block_id, address):
        block = IpBlock.find(ip_block_id)
        allocated_ip = IpAddress.get_by(ip_block_id=block.id, address=address)

        if allocated_ip and allocated_ip.locked():
            raise AddressLockedError()

        return (allocated_ip or block.allocate_ip(address=address))

    @classmethod
    def find_all_by_policy(cls, policy_id):
        return cls.find_all(policy_id=policy_id)

    @classmethod
    def allowed_by_policy(cls, ip_block, policy, address):
        return policy == None or policy.allows(ip_block.cidr, address)

    @classmethod
    def delete_all_deallocated_ips(cls):
        for block in db_api.find_all_blocks_with_deallocated_ips():
            block.update(is_full=False)
            block.delete_deallocated_ips()

    def is_ipv6(self):
        return IPNetwork(self.cidr).version == 6

    def subnets(self):
        return IpBlock.find_all(parent_id=self.id).all()

    def siblings(self):
        if not self.parent:
            return []
        return filter(lambda block: block != self, self.parent.subnets())

    def delete(self):
        for block in self.subnets():
            block.delete()
        IpAddress.find_all(ip_block_id=self.id).delete()
        super(IpBlock, self).delete()

    def policy(self):
        return Policy.get(self.policy_id)

    def get_address(self, address):
        return IpAddress.get_by(ip_block_id=self.id, address=address)

    def addresses(self):
        return IpAddress.find_all(ip_block_id=self.id).all()

    @cached_property
    def parent(self):
        return IpBlock.get(self.parent_id)

    def allocate_ip(self, port_id=None, address=None, **kwargs):
        if self.subnets():
            raise IpAllocationNotAllowedError(
                "Non Leaf block can not allocate IPAddress")
        if self.is_full:
            raise NoMoreAddressesError("IpBlock is full")

        if address is None:
            address = self._generate_ip_address(**kwargs)
        else:
            self._validate_address(address)

        if not address:
            self.update(is_full=True)
            raise NoMoreAddressesError("IpBlock is full")

        return IpAddress.create(address=address, port_id=port_id,
                                ip_block_id=self.id)

    def _generate_ip_address(self, **kwargs):
        if(self.is_ipv6()):
            address_generator = ipv6_address_generator_factory(self.cidr,
                                                               **kwargs)

            return find(lambda address: self.get_address(address) is None,
                                IpAddressIterator(address_generator))
        else:
            #TODO: very inefficient way to generate ips,
            #will look at better algos for this
            allocated_addresses = [ip.address for ip in self.addresses()]
            policy = self.policy()
            for ip in IPNetwork(self.cidr):
                if (IpBlock.allowed_by_policy(self, policy, str(ip))
                    and (str(ip) not in allocated_addresses)):
                    return str(ip)
            return None

    def _validate_address(self, address):

        if self.get_address(address) is not None:
            raise DuplicateAddressError()

        if not self.contains(address):
            raise AddressDoesNotBelongError(
                "Address does not belong to IpBlock")

        policy = self.policy()
        if not IpBlock.allowed_by_policy(self, policy, address):
            raise AddressDisallowedByPolicyError(
                "Block policy does not allow this address")

    def contains(self, address):
        return netaddr.IPAddress(address) in IPNetwork(self.cidr)

    def _overlaps(self, other_block):
        network = IPNetwork(self.cidr)
        other_network = IPNetwork(other_block.cidr)
        return network in other_network or other_network in network

    def find_allocated_ip(self, address):
        ip_address = IpAddress.find_by(ip_block_id=self.id, address=address)
        if ip_address == None:
            raise ModelNotFoundError("IpAddress Not Found")
        return ip_address

    def deallocate_ip(self, address):
        ip_address = IpAddress.find_by(ip_block_id=self.id, address=address)
        if ip_address != None:
            ip_address.deallocate()

    def delete_deallocated_ips(self):
        db_api.delete_deallocated_ips(
            deallocated_by=self._deallocated_by_date(), ip_block_id=self.id)

    def _deallocated_by_date(self):
        days_to_keep_ips = Config.get('keep_deallocated_ips_for_days', 2)
        return utils.utcnow() - timedelta(days=days_to_keep_ips)

    def subnet(self, cidr, network_id=None, tenant_id=None):
        network_id = network_id or self.network_id
        tenant_id = tenant_id or self.tenant_id
        return IpBlock.create(cidr=cidr, network_id=network_id,
                              parent_id=self.id, type=self.type,
                              tenant_id=tenant_id)

    def _validate_cidr_format(self):
        if not self._has_valid_cidr():
            self._add_error('cidr', "cidr is invalid")

    def _has_valid_cidr(self):
        try:
            IPNetwork(self.cidr)
            return True
        except Exception:
            return False

    def _validate_cidr_is_within_parent_block_cidr(self):
        parent = self.parent
        if parent and IPNetwork(self.cidr) not in IPNetwork(parent.cidr):
            self._add_error('cidr',
                            "cidr should be within parent block's cidr")

    def _validate_type(self):
        if not (self.type in self._allowed_types):
            self._add_error('type', "type should be one among {0}".format(
                    ", ".join(self._allowed_types)))

    def _validate_cidr(self):
        self._validate_cidr_format()
        if not self._has_valid_cidr():
            return
        self._validate_cidr_doesnt_overlap_for_root_public_ip_blocks()
        self._validate_cidr_is_within_parent_block_cidr()
        self._validate_cidr_does_not_overlap_with_siblings()
        if self._is_top_level_block_in_network():
            self._validate_cidr_doesnt_overlap_with_networked_toplevel_blocks()

    def _validate_cidr_doesnt_overlap_for_root_public_ip_blocks(self):
        if self.type != 'public':
            return
        for block in IpBlock.find_all(type='public', parent_id=None):
            if  self != block and self._overlaps(block):
                msg = "cidr overlaps with public block {0}".format(block.cidr)
                self._add_error('cidr', msg)
                break

    def _validate_cidr_does_not_overlap_with_siblings(self):
        for sibling in self.siblings():
            if self._overlaps(sibling):
                msg = "cidr overlaps with sibling {0}".format(sibling.cidr)
                self._add_error('cidr', msg)
                break

    def networked_top_level_blocks(self):
        if not self.network_id:
            return []
        blocks = db_api.find_all_top_level_blocks_in_network(self.network_id)
        return filter(lambda block: block != self and block != self.parent,
                      blocks)

    def _is_top_level_block_in_network(self):
        return not self.parent or self.network_id != self.parent.network_id

    def _validate_cidr_doesnt_overlap_with_networked_toplevel_blocks(self):
        for block in self.networked_top_level_blocks():
            if self._overlaps(block):
                self._add_error('cidr', "cidr overlaps with block {0}"
                                " in same network".format(block.cidr))
                break

    def _validate_belongs_to_supernet_network(self):
        if(self.parent and self.parent.network_id and
           self.parent.network_id != self.network_id):
            self._add_error('network_id',
                            "network_id should be same as that of parent")

    def _validate_belongs_to_supernet_tenant(self):
        if(self.parent and self.parent.tenant_id and
           self.parent.tenant_id != self.tenant_id):
            self._add_error('tenant_id',
                            "tenant_id should be same as that of parent")

    def _validate_parent_is_subnettable(self):
        if (self.parent and self.parent.addresses()):
            msg = "parent is not subnettable since it has allocated ips"
            self._add_error('parent_id', msg)

    def _validate_type_is_same_within_network(self):
        block = IpBlock.get_by(network_id=self.network_id)
        if(block and block.type != self.type):
            self._add_error('type', "type should be same within a network")

    def _validate(self):
        self._validate_type()
        self._validate_cidr()
        self._validate_existence_of('parent_id', IpBlock, type=self.type)
        self._validate_belongs_to_supernet_network()
        self._validate_belongs_to_supernet_tenant()
        self._validate_parent_is_subnettable()
        self._validate_existence_of('policy_id', Policy)
        self._validate_type_is_same_within_network()

    def _convert_cidr_to_lowest_address(self):
        if self._has_valid_cidr():
            self.cidr = str(IPNetwork(self.cidr).cidr)

    def _before_validate(self):
        self._convert_cidr_to_lowest_address()


class IpAddress(ModelBase):

    _data_fields = ['ip_block_id', 'address', 'port_id']

    @classmethod
    def _get_conditions(cls, raw_conditions):
        conditions = raw_conditions.copy()
        if 'address' in conditions:
            conditions['address'] = cls._formatted(conditions['address'])
        return conditions

    @classmethod
    def _formatted(cls, address):
        return IPAddress(address).format(dialect=ipv6_verbose)

    def _before_save(self):
        self.address = self._formatted(self.address)

    def ip_block(self):
        return IpBlock.get(self.ip_block_id)

    def add_inside_locals(self, ip_addresses):
        db_api.save_nat_relationships([
            {"inside_global_address_id": self.id,
             "inside_local_address_id": local_address.id}
            for local_address in ip_addresses])

    def deallocate(self):
        return self.update(marked_for_deallocation=True,
                           deallocated_at=utils.utcnow())

    def restore(self):
        self.update(marked_for_deallocation=False, deallocated_at=None)

    def inside_globals(self, **kwargs):
        return db_api.find_inside_globals_for(self.id, **kwargs)

    def add_inside_globals(self, ip_addresses):
        return db_api.save_nat_relationships([
            {"inside_global_address_id": global_address.id,
             "inside_local_address_id": self.id}
            for global_address in ip_addresses])

    def inside_locals(self, **kwargs):
        return db_api.find_inside_locals_for(self.id, **kwargs)

    def remove_inside_globals(self, inside_global_address=None):
        return db_api.remove_inside_globals(self.id, inside_global_address)

    def remove_inside_locals(self, inside_local_address=None):
        return db_api.remove_inside_locals(self.id, inside_local_address)

    def locked(self):
        return self.marked_for_deallocation

    def data_with_network_info(self):
        ip_block = self.ip_block()
        network_info = {'broadcast_address': ip_block.broadcast_address,
                        'gateway_address': ip_block.gateway_address,
                        'nameserver': Config.get('nameserver', None)}
        return dict(self.data().items() + network_info.items())


class Policy(ModelBase):

    _data_fields = ['name', 'description', 'tenant_id']

    def _validate(self):
        self._validate_presence_of('name')

    def delete(self):
        IpRange.find_all(policy_id=self.id).delete()
        IpOctet.find_all(policy_id=self.id).delete()
        IpBlock.find_all(policy_id=self.id).update(policy_id=None)
        super(Policy, self).delete()

    def create_unusable_range(self, **attributes):
        attributes['policy_id'] = self.id
        return IpRange.create(**attributes)

    def create_unusable_ip_octet(self, **attributes):
        attributes['policy_id'] = self.id
        return IpOctet.create(**attributes)

    @cached_property
    def unusable_ip_ranges(self):
        return IpRange.find_all(policy_id=self.id).all()

    @cached_property
    def unusable_ip_octets(self):
        return IpOctet.find_all(policy_id=self.id).all()

    def allows(self, cidr, address):
        if (any(ip_octet.applies_to(address)
                       for ip_octet in self.unusable_ip_octets)):
            return False
        return not any(ip_range.contains(cidr, address)
                       for ip_range in self.unusable_ip_ranges)

    def find_ip_range(self, ip_range_id):
        return IpRange.find_by(id=ip_range_id, policy_id=self.id)

    def find_ip_octet(self, ip_octet_id):
        return IpOctet.find_by(id=ip_octet_id, policy_id=self.id)


class IpRange(ModelBase):

    _columns = {'offset': data_types.integer, 'length': data_types.integer}
    _data_fields = ['offset', 'length', 'policy_id']

    def contains(self, cidr, address):
        end_index = self.offset + self.length
        end_index_overshoots_length_for_negative_offset = (self.offset < 0
                                                           and end_index >= 0)
        if end_index_overshoots_length_for_negative_offset:
            end_index = None
        return IPAddress(address) in IPNetwork(cidr)[self.offset:end_index]

    def _validate(self):
        self._validate_positive_integer('length')


class IpOctet(ModelBase):

    _columns = {'octet': data_types.integer}
    _data_fields = ['octet', 'policy_id']

    @classmethod
    def find_all_by_policy(cls, policy_id):
        return cls.find_all(policy_id=policy_id)

    def applies_to(self, address):
        return self.octet == IPAddress(address).words[-1]


class Network(ModelBase):

    @classmethod
    def find_by(cls, id, tenant_id=None):
        ip_blocks = IpBlock.find_all(network_id=id, tenant_id=tenant_id).all()
        if(len(ip_blocks) == 0):
            raise ModelNotFoundError("Network {0} not found".format(id))
        return cls(id=id, ip_blocks=ip_blocks)

    @classmethod
    def find_or_create_by(cls, id, tenant_id=None):
        try:
            return cls.find_by(id=id, tenant_id=tenant_id)
        except ModelNotFoundError:
            ip_block = IpBlock.create(cidr=Config.get('default_cidr'),
                                      network_id=id, tenant_id=tenant_id,
                                      type="private")
            return cls(id=id, ip_blocks=[ip_block])

    def allocate_ips(self, addresses=[], **kwargs):
        if addresses:
            return filter(None, [self._allocate_specific_ip(address, **kwargs)
                    for address in addresses])

        ips = [self._allocate_first_free_ip(blocks, **kwargs)
               for blocks in self._block_partitions()]

        if not any(ips):
            raise NoMoreAddressesError("ip blocks in this network are full")

        return filter(None, ips)

    def _block_partitions(self):
        return [[block for block in self.ip_blocks
                 if not block.is_ipv6()],
                [block for block in self.ip_blocks
                 if block.is_ipv6()]]

    def _allocate_specific_ip(self, address, **kwargs):
        ip_block = utils.find(lambda ip_block: ip_block.contains(address),
                              self.ip_blocks)
        if(ip_block is not None):
            try:
                return ip_block.allocate_ip(address=address, **kwargs)
            except DuplicateAddressError:
                pass

    def _allocate_first_free_ip(self, ip_blocks, **kwargs):
        for ip_block in ip_blocks:
            try:
                return ip_block.allocate_ip(**kwargs)
            except NoMoreAddressesError:
                pass


def models():
    return {'IpBlock': IpBlock, 'IpAddress': IpAddress, 'Policy': Policy,
            'IpRange': IpRange, 'IpOctet': IpOctet}


class NoMoreAddressesError(MelangeError):

    def _error_message(self):
        return "no more addresses"


class DuplicateAddressError(MelangeError):

    def _error_message(self):
        return "Address is already allocated"


class AddressDoesNotBelongError(MelangeError):

    def _error_message(self):
        return "Address does not belong here"


class AddressLockedError(MelangeError):

    def _error_message(self):
        return "Address is locked"


class ModelNotFoundError(MelangeError):

    def _error_message(self):
        return "Not Found"


class DataMissingError(MelangeError):

    def _error_message(self):
        return "Data Missing"


class AddressDisallowedByPolicyError(MelangeError):

    def _error_message(self):
        return "Policy does not allow this address"


class IpAllocationNotAllowedError(MelangeError):

    def _error_message(self):
        return "Ip Block can not allocate address"


class InvalidModelError(MelangeError):

    def __init__(self, errors, message=None):
        self.errors = errors
        super(InvalidModelError, self).__init__(message)

    def __str__(self):
        return "The following values are invalid: %s" % str(self.errors)

    def _error_message(self):
        return str(self)


def sort(iterable):
    return sorted(iterable, key=lambda model: model.id)
