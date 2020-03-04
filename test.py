#!/usr/bin/env python3
# pylint: disable=invalid-name,no-member,line-too-long,import-error,missing-function-docstring,bad-continuation

""" URL blocking service unit test cases """

import json
import unittest

from app import UrlManagement, app


class UrlTests(unittest.TestCase):
    """ Basic unit tests """

    def tearDown(self):
        # Delete everything
        UrlManagement.empty()

    def setUp(self):
        # Empty the redis database
        UrlManagement.empty()

        self.app = app.test_client()

        # Inject testing data (temporary for development, testing will use fixtures)
        UrlManagement.set_domain('www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 111111111,
                'safe': False
            }])

        UrlManagement.set_domain('www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 222222222,
            }])

        UrlManagement.set_domain('www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 333333333,
            }])

        UrlManagement.set_domain('badguys.cisco.com:443',
            safe=False)

        UrlManagement.set_domain('badguys.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            safe=False,
            qs=[{'courseId': 333333333}, {'courseId': 1234, 'safe': True}])

    def test_for_404_at_root_url(self):
        response = self.app.get('/', follow_redirects=False)

        # Expect that the root URL returns 404
        self.assertEqual(response.status_code, 404)

    def test_with_multiple_query_parameters(self):
        # Expect that the root URL returns 403, because courseId=222222222 is safe, but courseId=111111111 is not safe
        response = self.app.get('/urlinfo/1/www.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=222222222&courseId=111111111')
        self.assertEqual(response.status_code, 403)

    def test_safe_url(self):
        # Expect that the root URL returns 200, because courseId=1234 is safe
        response = self.app.get('/urlinfo/1/www.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=1234')
        self.assertEqual(response.status_code, 200)

        # Expect that the root URL returns 200, because courseId=1234 is safe
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=1234')
        self.assertEqual(response.status_code, 200)

    def test_for_unsafe_url(self):
        # Expect that the root URL returns 403, because courseId=111111111 is not safe
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=111111111')       
        self.assertEqual(response.status_code, 403)

    def test_for_url_with_and_without_path(self):
        # Expect that the root URL returns 403, because URL is not safe
        response = self.app.get('/urlinfo/1/www.cisco.com:443/')
        self.assertEqual(response.status_code, 200)

        # Expect that the root URL returns 403, because URL is not safe
        response = self.app.get('/urlinfo/1/www.cisco.com:443')
        self.assertEqual(response.status_code, 200)

        # Expect that the root URL returns 403, because URL is not safe
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/')
        self.assertEqual(response.status_code, 403)

        # Expect that the root URL returns 403, because URL is not safe
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443')
        self.assertEqual(response.status_code, 403)

    def test_delete_query_string(self):
        # Request to the domain
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=1234')

        # Expect that the root URL returns 403
        self.assertEqual(response.status_code, 200)

        um = UrlManagement.get_instance_for_domain('badguys.cisco.com:443')

        # Delete the request path
        um.delete(
            'badguys.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{'courseId': 1234}])

        # Request to the domain
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html?courseId=1234')

        # Expect that the root URL returns 200
        self.assertEqual(response.status_code, 403)

    def test_delete_domain_path(self):
        # Request to the domain
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html')

        # Expect that the root URL returns 403
        self.assertEqual(response.status_code, 403)

        um = UrlManagement.get_instance_for_domain('badguys.cisco.com:443')

        # Delete the request path
        um.delete(
            'badguys.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html')

        # Query the domain and expect the URL returns 200 OK
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443')

        # Expect that the root URL returns 403 because the root of badguys.cisco.com is not marked safe
        self.assertEqual(response.status_code, 403)

    def test_delete_domain(self):
        # Request to the domain
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443')

        # Expect that the root URL returns 403
        self.assertEqual(response.status_code, 403)

        um = UrlManagement.get_instance_for_domain('badguys.cisco.com:443')

        # Delete the domain
        um.delete('badguys.cisco.com:443')

        # Query the domain and expect the URL returns 200 OK
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443')

        # Expect that the root URL returns 200, our default is to allow
        # if the domain is not listed or marked safe
        self.assertEqual(response.status_code, 200)

    def test_api_get_domain_list(self):
        response = self.app.get('/admin/domains')

        # Our API should return 200 OK with a list of domains
        self.assertEqual(response.status_code, 200)

        # There should be two domains loaded by default from our testing data
        # badguys.cisco.com:443 and www.cisco.com:443
        self.assertEqual(len(json.loads(response.data)), 2)

    def test_api_get_domain(self):
        # Make sure we get a 200 response back from a valid domain
        response = self.app.get('/admin/domain/badguys.cisco.com:443')
        self.assertEqual(response.status_code, 200)

        # Make sure we get a 404 response back from a invalid domain
        response = self.app.get('/admin/domain/some.domain.that.is.non.existant:443')
        self.assertEqual(response.status_code, 404)

    def test_api_delete_domain(self):
        # Make sure we get a 200 response back from a valid domain
        response = self.app.get('/admin/domain/badguys.cisco.com:443')
        self.assertEqual(response.status_code, 200)

        # Make sure we get a 200 response back from a valid domain
        response = self.app.delete('/admin/domain/badguys.cisco.com:443')

        self.assertEqual(response.status_code, 204)

        # Make sure we get a 404 response back from a invalid domain
        response = self.app.delete('/admin/domain/some.domain.that.is.non.existant:443')
        self.assertEqual(response.status_code, 404)

    def test_api_create_domain(self):
        valid_domain = {
            "site.cisco.com:443": {
                "/safe": {
                    "safe": True
                },
                "/unsafe": {
                    "safe": False
                }
            }
        }

        # Should create our domain
        response = self.app.post(
            '/admin/domains',
            content_type='application/json',
            data=json.dumps(valid_domain))

        self.assertEqual(response.status_code, 202)

        # Expect that the / URL returns 200
        response = self.app.get('/urlinfo/1/site.cisco.com:443/')
        self.assertEqual(response.status_code, 200)

        # Expect that the blank root URL returns 200
        response = self.app.get('/urlinfo/1/site.cisco.com:443')
        self.assertEqual(response.status_code, 200)

        # Expect that the blank root URL returns 200
        response = self.app.get('/urlinfo/1/site.cisco.com:443/safe')
        self.assertEqual(response.status_code, 200)

        # Expect that the blank root URL returns 200
        response = self.app.get('/urlinfo/1/site.cisco.com:443/unsafe')
        self.assertEqual(response.status_code, 200)

        # Expect a conflict
        response = self.app.post(
            '/admin/domains',
            content_type='application/json',
            data=json.dumps(valid_domain))

        self.assertEqual(response.status_code, 409)

        # Expect a failure because no domain was provided
        response = self.app.post(
            '/admin/domains',
            content_type='application/json',
            data=json.dumps(valid_domain.get("site.cisco.com:443")))

        self.assertEqual(response.status_code, 406)

        invalid_domain = {
            "valid.cisco.com:443": {
                "/safe": {
                    "safe": []
                },
                "/unsafe": {
                    "safe": "hello world"
                }
            }
        }

        # Send some invalid JSON, it should fail because it does not
        # conform to the JSON schema
        response = self.app.post(
            '/admin/domains',
            content_type='application/json',
            data=json.dumps(invalid_domain))

        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
