#!/usr/bin/env python3
# pylint: disable=invalid-name,no-member,line-too-long,import-error,missing-function-docstring

""" URL blocking service unit test cases """

import unittest

from app import UrlManagement, app


class UrlTests(unittest.TestCase):
    """ Basic unit tests """

    def setUp(self):
        self.app = app.test_client()

        self.um = UrlManagement()

        # Empty the redis database
        self.um.empty()

        # Inject testing data (temporary for development, testing will use fixtures)
        self.um.set(
            'www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 111111111,
                'safe': False
            }])

        self.um.set(
            'www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 222222222,
            }])

        self.um.set(
            'www.cisco.com:443',
            path='/c/en/us/training-events/training-certifications/trainingcatalog/course-selector.html',
            qs=[{
                'courseId': 333333333,
            }])

        self.um.set('badguys.cisco.com:443', safe=False)

        self.um.set(
            'badguys.cisco.com:443',
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

    def test_for_url_without_path_and_query_string(self):
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

        # Delete the request path
        self.um.delete(
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

        # Delete the request path
        self.um.delete(
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

        # Delete the domain
        self.um.delete('badguys.cisco.com:443')

        # Query the domain and expect the URL returns 200 OK
        response = self.app.get('/urlinfo/1/badguys.cisco.com:443')

        # Expect that the root URL returns 200, our default is to allow
        # if the domain is not listed or marked safe
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    # import logging
    # import json

    # logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    unittest.main()
