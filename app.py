#!/usr/bin/env python3
# pylint: disable=invalid-name,no-member,line-too-long,unused-argument,bad-continuation

""" URL blocking service """

import math
import re
import string
import time
from urllib.parse import urlparse

import redis
import tldextract
from flask import Flask, Response, abort, json
from flask_restful import Api, Resource, request
from jsonschema import validate
from jsonschema.exceptions import ValidationError

app = Flask(__name__)
api = Api(app)

# Validate our JSON
JSON_SCHEMA = {
	"$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,

    "patternProperties": {
      "^.*$": {
        "type": "object",
        "$ref": "#/definitions/domain"
      }
    },
      
    "definitions": {
      "additionalProperties": False,
      "domain": {
        "properties": {
          "safe": { "type": "boolean" },
          "updated": {
            "type": "number"
          }          
        },
        "patternProperties": {
          "^(?!.*safe).*$": {
            "type": "object",
            "$ref": "#/definitions/path"
          }
        }          
      },

      "path": {
        "properties": {
          "safe": { "type": "boolean" },
          "qs": { 
            "type": "array", 
            "items": {
              "type": "object",
              "$ref": "#/definitions/qs"
            }
          },
          "updated": {
            "type": "number"
          },
          "additionalProperties": False
        }
      },

      "qs": {
        "properties": {
          "safe": { "type": "boolean" },
          "updated": {
            "type": "number"
          }          
        },
        "patternProperties": {
          "^(?!.*safe).*$": {
            "type": "object",
            "$ref": "#/definitions/path"
          }
        }
      }
    }
  }

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
REDIS_DB_MAX_ID = 16


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


class UrlManagementDomainsAPI(Resource):
    """ Domain List API """

    def get(self, **kwargs):
        """ List of Domains """
        response = []

        for index in range(REDIS_DB_MAX_ID):
            c = redis.StrictRedis(
                host=kwargs.get('host', 'localhost'),
                port=kwargs.get('port', 6379),
                db=kwargs.get('db', index),
                decode_responses=True)

            response.extend(c.keys('*'))

        return response

    def post(self, **kwargs):
        """
        Simple post method to create a new domain. There
        is no validation in any of these commands yet
        that will santize the data structure.
        """

        try:
            # Get the raw JSON data
            data = request.get_json(force=True)

            domains = list(data)

            if len(domains) != 1 or not domains[0]:
                return app.response_class(
                    response='Domain missing in request payload',
                    status=406)

            # Get the domain name from the raw JSON
            domain = domains[0]

            um = UrlManagement.get_instance_for_domain(domain)

            if um.get_domain(domain):
                return app.response_class(
                    response='Domain already exists',
                    status=409)

            validate(instance=data.get(domain), schema=JSON_SCHEMA)

            # Create the new domain
            um.create(domain, json.dumps(data.get(domain)))

            if um.get_domain(domain):
                return Response(
                    response='Domain created',
                    status=202)

            # An error occurred
            return Response(
                response='Domain not created (server error)',
                status=500)

        except ValidationError:
            # If the validation fails, return 400 Bad Request since
            # the data was invalid and did not conform to our
            # JSON schema
            return app.response_class(response='Validation error', status=500)


class UrlManagementDomainAPI(Resource):
    """ Domain Get API """
    redis = None

    def get(self, domain_name, **kwargs):
        """ Get a details for a specific domain """
        try:
            um = UrlManagement.get_instance_for_domain(domain_name)

            domain = um.get_domain(domain_name)

            if not domain:
                abort(404, 'Domain not found')

            return domain

        except ValidationError:
            abort(404, 'Domain not found')

    def delete(self, domain_name):
        """
        Simple delete method for now to delete a domain,
        this will not delete specific paths or query strings
        yet, so the entire entry will need to be reconstructed.
        """

        um = UrlManagement.get_instance_for_domain(domain_name)

        if um.get_domain(domain_name):
            um.delete(domain_name)

            # 204 No Content is a popular response for DELETE
            return "Domain deleted", 204

        abort(404, "Domain not found")


class UrlManagement:
    """ URL Management """

    # Redis connection object
    c = None

    @classmethod
    def get_instance_for_domain(cls, domain_name):
        """ Database shard """
        tld = tldextract.extract(domain_name)

        db = SHARD_DB_ID.get(tld.domain[0], 0)

        return cls(db=db)

    @staticmethod
    def empty(*args, **kwargs):
        """ Flush the redis cache (destructive operation); used by tests """
        if kwargs.get('db', None):
            c = redis.StrictRedis(
                host=kwargs.get('host', 'localhost'),
                port=kwargs.get('port', 6379),
                db=kwargs.get('db'),
                decode_responses=True)
            c.flushall()
        else:
            for index in range(REDIS_DB_MAX_ID):
                c = redis.StrictRedis(
                    host=kwargs.get('host', 'localhost'),
                    port=kwargs.get('port', 6379),
                    db=index,
                    decode_responses=True)

                c.flushall()

        return True

    @classmethod
    def set_domain(cls, domain_name, *args, **kwargs):
        """
        Since we're using separate databases now we need
        this for testing so we can inject fixtures into
        the correct database during testing
        """

        c = cls.get_instance_for_domain(domain_name)

        return c.set(domain_name, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        """ Database number for requests """
        self.c = redis.StrictRedis(
            host=kwargs.get('host', 'localhost'),
            port=kwargs.get('port', 6379),
            db=kwargs.get('db', 0),
            decode_responses=True)

    def create(self, domain_name, data):
        """ Create a domain """
        return self.c.set(domain_name, data)

    def get_domain(self, domain_name):
        """ Public method for now while we test """
        return self._get_domain(domain_name)

    def _get_domain(self, domain_name):
        """ Return domain mapping so we don't keep repeating ourselves """

        # If the domain exists, we'll fetch the existing metadata and
        # so that we can make an update, otherwise we'll start with
        # a new uninitalized hash
        mapping = self.c.exists(domain_name) \
            and self.c.get(domain_name) \
            or {}

        # Convert JSON encoded payload to an object
        if isinstance(mapping, str):
            mapping = json.loads(mapping)

        if mapping:
            return mapping

        return {}

    def delete(self, domain_name, **kwargs):
        """ Remove domain, path or query string """
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

                self.c.set(domain_name, json.dumps(mapping))
                return True
        elif domain_name:
            # Delete the domain and all children
            self.c.delete(domain_name)

            return self.c.exists(domain_name)

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

        self.c.set(domain_name, json.dumps(mapping))
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
        mapping = self._get_domain(domain_name)

        if not mapping:
            # Our default is to return safe URLs
            app.logger.debug(f"Domain {domain_name} could not be located")

            return mapping

        # Otherwise, Inherit the safe attribute from the domain, if it is
        # set.  If it is not set, then default to the existing is_safe
        # parameter, in this case would always be true at this point.
        is_safe = mapping.get('safe', is_safe)

        # If the request path is empty (or None).
        # If the mapping path is empty (None, {}).
        # If the request path is not in the mapping path array.
        #
        # If the URL is not safe, return an Exception as there is
        # no further processing to perform, or return the existing
        # mapping if the URL is safe.

        c1 = request_path
        c2 = 'path' in mapping
        c3 = c2 and request_path in mapping['path']

        # If all of the above conditions do not match (cleaner to read)
        if (c1 or c1 == '') and not all([c2, c3]):
            if not is_safe:
                raise UrlManagementException(403, f"Unsafe URL {request_path}")

            return mapping

        # Determine if the path is safe
        is_safe = mapping['path'][request_path].get('safe', is_safe)

        # Regular expression match:
        #
        # * cisco.com// (and any additional slashes)
        # * cisco.com/
        # * cisco.com
        if request_path and re.search(r'^[\/ ]+', request_path):
            # Since attributes may have the same key, we need to use multi=True
            # https://tedboy.github.io/flask/generated/generated/werkzeug.ImmutableMultiDict.iteritems.html

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

        tld = tldextract.extract(updated_request_url)

        # Our default redis database
        url_management = UrlManagement.get_instance_for_domain(
            ".".join([tld.domain, tld.suffix]))

        # Python bug in urlparse(), scheme parameter does not change the scheme
        parts = urlparse(updated_request_url)

        url_management.get(parts.netloc, path=parts.path, qs=request.args)

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


api.add_resource(UrlManagementDomainsAPI, '/admin/domains')
api.add_resource(UrlManagementDomainAPI, '/admin/domain/<string:domain_name>')

if __name__ == '__main__':
    app.run(port='8080', debug=True)
