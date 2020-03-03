#!/usr/bin/env python3
# pylint: disable=invalid-name,no-member,line-too-long

""" URL blocking service """

import math
import re
import string
import time
from urllib.parse import urlparse

import redis
# import tldextract
from flask import Flask, json
from flask_restful import request

app = Flask(__name__)

# Divide each letter in the alphabet by 2, and the domain
# that begins with that letter will be our database number
SHARD_DB_ID_LETTER = {
    k: math.floor(list(string.ascii_lowercase).index(k) / 2) for k in list(string.ascii_lowercase)
}

SHARD_DB_ID_DIGIT = {
    str(k): k for k in range(0, 10)
}

SHARD_DB_ID = {
    **SHARD_DB_ID_DIGIT,
    **SHARD_DB_ID_LETTER
}


class UrlManagementException(Exception):
    """
    Exception implementation as linter does not allow us to use
    the Exception class as its too generic.  This is only to satisfy
    the linter for now.
    """
    response_code = 200
    response_message = ""

    def __init__(self, response_code, response_message, *args, **kwargs):
        self.response_code = response_code
        self.response_message = response_message

        super().__init__(*args, **kwargs)


class UrlManagement(object):
    """ URL Management """
    def __init__(self, **kwargs):
        self.redis = redis.StrictRedis(
            host=kwargs.get('host', 'localhost'),
            port=kwargs.get('port', 6379),
            db=kwargs.get('db', 0),
            decode_responses=True)

    def empty(self):
        """ Flush the redis cache (destructive operation); used by tests """
        return self.redis.flushall()

    def get_domain(self, domain_name):
        """ Public method for now while we test """
        return self._get_domain(domain_name)

    def _get_domain(self, domain_name):
        """ Return domain mapping so we don't keep repeating ourselves """

        # If the domain exists, we'll fetch the existing metadata and
        # so that we can make an update, otherwise we'll start with
        # a new uninitalized hash
        mapping = self.redis.exists(domain_name) \
            and self.redis.get(domain_name) \
            or {}

        # Convert JSON encoded payload to an object
        if isinstance(mapping, str):
            mapping = json.loads(mapping)

        return mapping

    def delete(self, domain_name, **kwargs):
        """ Delete domain, path or query string """
        request_path = kwargs.get('path', None)
        request_qs = kwargs.get('qs', [])

        mapping = self._get_domain(domain_name)

        if not any(mapping):
            # If mapping is empty, return
            return False

        if all([request_path, request_qs]):
            # Delete by request path and query set
            request_qs = [dict(**qs, **{'_delete': True}) for qs in request_qs]

            return self.set(domain_name, path=request_path, qs=request_qs)
        elif request_path:
            # Delete by request path
            if 'path' in mapping.keys() and request_path in mapping['path'].keys():
                del mapping['path'][request_path]

                self.redis.set(domain_name, json.dumps(mapping))
                return True
        elif domain_name:
            # Delete the domain and all children
            self.redis.delete(domain_name)

            return self.redis.exists(domain_name)

        return False

    def set(self, domain_name, **kwargs):        
        """ Set details for a domain """
        request_path = kwargs.get('path', None)
        request_qs = kwargs.get('qs', [])
        updated = kwargs.get('updated', math.floor(time.time()))
        safe = kwargs.get('safe', None)

        mapping = self._get_domain(domain_name)

        # If there is already an existing entry for the domain and path,
        # update any query string values as well that may have been
        # added since the last request.
        if request_path and 'path' in mapping.keys() and request_path in mapping['path'].keys():

            # Merge the safe parameter for existing request path, if supplied.
            if safe is not None:
                mapping['path'][request_path]['safe'] = safe

            for current_qs in request_qs:
                # Don't use the updated key to match as its unique to the
                # time the last time the object was created/updated.
                current_qs_keys = current_qs.keys() - ["updated", "safe", "_delete"]

                mapping_qs = mapping['path'][request_path]['qs']

                for current_qs_key in current_qs_keys:
                    for mapping_qs_index, mapping_qs_entry in enumerate(mapping_qs):
                        mapping_qs_keys = mapping_qs_entry.keys() - ["updated", "safe", "_delete"]

                        # Yes, there are many levels of nesting here, break it down later
                        if current_qs_key in mapping_qs_keys and current_qs[current_qs_key] == mapping_qs_entry[current_qs_key]:
                            if '_delete' in current_qs.keys():
                                # Delete the element at a specific index, otherwise just update
                                # or add to the list (array)

                                del mapping['path'][request_path]['qs'][mapping_qs_index]
                            else:
                                # Retain logic to update an existing entry
                                mapping['path'][request_path]['qs'][mapping_qs_index].update({
                                    'updated': updated,
                                    'safe': current_qs.get('safe', safe)
                                })
                        elif not current_qs.get('_delete', False):
                            # Only add new entries if they don't have a _delete flag
                            mapping['path'][request_path]['qs'].append({
                                current_qs_key: current_qs[current_qs_key],
                                'updated': updated,
                                'safe': current_qs.get('safe', safe)
                            })
        else:
            # Add an updated timestamp to newly created objects too
            for qs in request_qs:
                if 'updated' not in qs.keys():
                    qs['updated'] = updated

            if request_path:
                # If 'path' does not exist in the hash yet, add it for the
                # first request path entry

                if 'path' not in mapping.keys():
                    mapping['path'] = {}

                mapping['path'][request_path] = {
                    'qs': request_qs,
                    'updated': updated
                }

                if safe is not None:
                    mapping['path'][request_path]['safe'] = safe

            else:
                # If no request path provided, mark the domain
                mapping = {
                    'updated': updated,
                }

                if safe is not None:
                    mapping['safe'] = safe

        self.redis.set(domain_name, json.dumps(mapping))
        return True

    def get(self, domain_name, **kwargs):
        """ Get details about a domain """

        # Calculated value from the safe attribute of a domain, request path or query
        # string attribute.
        is_safe = True

        # Our request path
        request_path = kwargs.get('path', None)

        # If multiple query string parameters are provided, all of the
        # parameters must exist for a match to be successful.
        request_qs = kwargs.get('qs', [])

        # If the domain exists, we'll fetch the existing metadata and
        # so that we can make an update, otherwise we'll start with
        # a new uninitalized hash
        if not self.redis.exists(domain_name):
            app.logger.debug(f"Domain {domain_name} could not be located")

            return {}

        mapping = self._get_domain(domain_name)

        # Inherits the safe attribute from the domain (if set); otherwise
        # default to True
        is_safe = mapping.get('safe', is_safe)

        # If a request path was provided, determine if the path is safe by
        # checking the safe parameter of the hash, if it does not exist
        # then use the default from the domain.
        if request_path in mapping['path'].keys():
            is_safe = mapping['path'][request_path].get('safe', is_safe)

        # Our Request path should always be set, unless we're looking at
        # the root/index of domain, as this would be a unecessary check
        # as we'll be inherting from the domain level anyways.

        # Regular expression match:
        #
        # * cisco.com// (and any additional slashes)
        # * cisco.com/
        # * cisco.com
        if request_path and re.search(r'^[\/ ]+', request_path):
            if request_path not in mapping['path'].keys():
                if is_safe:
                    app.logger.debug(f"Path {request_path} not registered yet")

                    return mapping
                else:
                    # If the request_path is not defined, and the domain is not safe
                    # raise an Exception that this is not a safe location.
                    raise UrlManagementException(403, f"Unsafe URL {request_path}")
            else:
                # If the request path is defined, then inherit the safe value from the
                # request_path so we can block the domain for example, but give permission
                # based on the request_path.
                is_safe = mapping['path'][request_path].get('safe', True)

            # Since attributes may have the same key, we need to use multi=True
            # https://tedboy.github.io/flask/generated/generated/werkzeug.ImmutableMultiDict.iteritems.html#werkzeug.ImmutableMultiDict.iteritems

            for (request_qs_key, request_qs_value) in request_qs.items(multi=True):
                # app.logger.debug(f"Validating query parameter ({request_qs_key}={request_qs_value})")

                for mapping_qs_value in mapping['path'][request_path]['qs']:
                    # If request_qs_key (the query string key) is in the stored mapping query parameters
                    # and the request_qs_value (the query string value) equals the stored mapping query parameter value
                    # and it is marked as an unsafe parameter due to its value, then raise an exception
                    # which should return a 403 back to the calling client/service.
                    mapping_qs_keys = mapping_qs_value.keys() - ['updated', 'safe']

                    # Determine if the query parameter is unsafe
                    if request_qs_key in mapping_qs_keys and str(mapping_qs_value[request_qs_key]) == str(request_qs_value):
                        # If the query parameter already marked the query unsafe,
                        # don't allow another query parameter to permit it.
                        is_safe = mapping_qs_value.get('safe', is_safe)

                        if not is_safe:
                            # If the safe boolean every becomes false, then we'll abort right away
                            # and stop processing query strings
                            raise UrlManagementException(403, f"Unsafe URL {request_path}")

        # The request path was not set, or querying the index/root
        # of the domain, therefore, if the domain is not safe
        # we'll block the request
        if not is_safe:
            raise UrlManagementException(403, f"Unsafe URL {request_path}")

        # Finally return our mapping being that the request was a valid.
        return mapping


@app.route('/urlinfo/1/<path:request_url>', methods=[
    'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'UPDATE'])
def get_request_url(request_url):
    """
    Provides the URL blocking service interface to handle
    GET, POST, PUT, PATCH, DELETE, and UPDATE HTTP methods
    """

    try:
        updated_request_url = request_url

        if not re.search(r'^(http[s]?)', updated_request_url):
            updated_request_url = f'https://{request_url}'

        # tld = tldextract.extract(updated_request_url)
        #
        # db = SHARD_DB_ID.get(tld.domain[0])
        # app.logger.debug(f"Using database {db} for {tld.domain}")

        # Our default redis database
        db = 0

        # Python bug in urlparse(), scheme parameter does not change the scheme
        parts = urlparse(updated_request_url)

        um = UrlManagement(db=db)
        um.get(parts.netloc, path=parts.path, qs=request.args)

        return app.response_class(
            status=200,
            response=json.dumps({
                'status': 'success'
            }),
            mimetype='application/json')

    except UrlManagementException as e:
        return app.response_class(
            status=e.response_code,
            response=json.dumps({
                'status': 'fail',
                'message': e.response_message
            }),
            mimetype='application/json')


if __name__ == '__main__':
    app.run(port='8080', debug=True)
