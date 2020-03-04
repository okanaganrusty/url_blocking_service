# URL Blocking Service

[[toc]]

As per the URL lookup service request, I have some questions to help with my discovery process.  Below are my design considerations for the project which we can review in further detail. Could we schedule a discussion to agree on requirements, design and roadmap.  

The URL lookup service is going to be receiving a copy of all HTTP methods your webserver receives, and not just a subset of only GET/POST requests, the service will need to be distributed across your regions and availability zones, scalable, and non-blocking.  Including that the caching layer should be shared across all URL lookup service deployments in your environment.

## Dependencies

### Redis Caching Server

You need to have a redis server running locally.  If you are on a Mac, I suggest using Homebrew on Mac OS X.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"

brew install redis
brew service start redis
```

Alternatively, we've supplied a docker-composer to initialize a local redis server.  If you run the following command, it will build a redis environment for you exposing TCP port 6379 so this server application and testing can make use of it.

```bash
docker-compose up
```

## Setup Process

1. Install a Python virtual environment
2. Activate the Python virtual environment
3. Install the dependencies into the virtual environment
4. Run the software
5. Run the test cases

```bash
# Install the virtual environment for your native python installation
pip3 install virtualenv

# Create a folder for the virtual environment
mkdir $HOME/.venv

# Create a virtual environment
virtualenv $HOME/.venv

# Activate the virtualenv
source $HOME/.venv/bin/activate

# Install dependencies
pip3 install -r requirements.txt

# To run the server application (app.py)
./run.sh

# To run the unit tests to validate functionality (test.py)
./test.sh
```

## Design

In consideration of scaling of the service, I would like to propose that the scaling be based on splitting the request domain into chunks, rather than storing the entire domain itself, storing the top-level domain and parent domain as a single key, and any sub-domains into their own keys beneath the parent domain.  This way the number of requests towards a top-level domain or sub-domain of a parent, which in addition would allow distribution of the data to separate datasets based on domain, including indexing the path and query parameters beneath the domain. Each query parameter will have a safe parameter and a associated cost to limit the maximum number of query parameters.

For example (in a JSON structure):

* The dataset is indexed based on the top-level domain and parent domain, with sub-domains defined as in the child key of the parent.  The application will determine the datasource based on the top-level and parent domain.

* Depending on the cache/database layer chosen:
  * Caching layers such as redis may have an expires flag set allowing automatic purging of the data.  Use of a caching layer is our recommended approach.
  * Databases layers such as no SQL or a RDBMS may will need to be cleaned up by running a periodic task or job.

* The dataset has a `safe` flag marking whether a request may or may not be safe towards the requested domain, path and query string.

* The dataset is being validated by a JSON schema to ensure all data is well-formed.

---

### Request Formats

#### URL Blocking Service Requests

##### Successful Request

Example URL

`https://www.cisco.com/c/en/us/training-events/training-certifications/training-catalog/course-selector.html?courseId=987654321`

###### Request

```plain
GET /urlinfo/1/www.cisco.com:443/c/en/us/training-events/training-certifications/training-catalog/course-selector.html?courseId=987654321 HTTP/1.1
...
```

###### Response

```plain
HTTP/1.1 200 OK
```

##### Blocked Request

Example URL

`https://badguy.cisco.com/c/en/us/training-events/training-certifications/training-catalog/course-selector.html?courseId=987654321&evil=DELETE%20*%20FROM%20users`

###### Request

```plain
GET /urlinfo/1/badguy.cisco.com:443/c/en/us/training-events/training-certifications/training-catalog/course-selector.html?courseId=987654321&evil=DELETE%20*%20FROM%20users HTTP/1.1
```

###### Response

```plain
HTTP/1.1 403 Forbidden
```

---

#### URL Blocking Service Management Requests

##### List of Domains

Provide a list of domains.

Method: `GET`
URL: `https://[URL BLOCKING SERVICE FQDN or IP]/urlinfo/1/admin/domains`

HTTP Responses

* HTTP 200 (OK) with JSON payload (the response may be empty)

Example Request and Response Payload

```bash
curl -v http://localhost:8080/admin/domains

< HTTP/1.0 200 OK
< Content-Type: application/json
< Content-Length: 21
< Server: Werkzeug/1.0.0 Python/3.8.1
< Date: Wed, 04 Mar 2020 18:10:36 GMT
```

```json
{
    "safe": true
}
```

##### Get Details of a Domain

Get details of a Domain

Method: `GET`
URL: `https://[URL BLOCKING SERVICE FQDN or IP]/admin/domain/<domain>`

HTTP Responses

* HTTP 200 (OK) with JSON payload

Example Request and Response Payload #1

```bash
curl -v http://localhost:8080/admin/domain/www.cisco.com:443

< HTTP/1.0 200 OK
< Content-Type: application/json
< Content-Length: 21
< Server: Werkzeug/1.0.0 Python/3.8.1
< Date: Wed, 04 Mar 2020 18:11:11 GMT
```

```json
{
    "safe": true
}
```

Example Request and Response Payload #2 

```bash
curl -X GET 'http://localhost:8080/admin/domain/badguys.cisco.com:443'

< HTTP/1.0 200 OK
< Content-Type: application/json
< Content-Length: 21
< Server: Werkzeug/1.0.0 Python/3.8.1
< Date: Wed, 04 Mar 2020 18:11:11 GMT
```

```json
{
    "path": {
        "/safe": {
            "qs": [
                {
                    "evil": "1234",
                    "safe": false
                }
            ],
            "safe": true
        }
    },
    "safe": false
}
```

##### Delete a Domain, Path or Query String

Delete a Domain, Path or Query String from an element.

Method: `DELETE`
URL: `https://[URL BLOCKING SERVICE FQDN or IP]/admin/domain/<domain>`

URL Parameters

* `domain` (string) The domain you would like to return contents of the data
* `path` (string) The path you want to delete (including all children)
* `qs` (string) The query parameter you want to delete

HTTP Responses

* HTTP 204 (Accepted): If resource was deleted.
* HTTP 404 (Not Found): If resource is not located.

Example Response Payload

```bash
curl -v -X DELETE http://localhost:8080/admin/domain/www.cisco.com:443

 HTTP/1.0 204 NO CONTENT
< Content-Type: application/json
< Server: Werkzeug/1.0.0 Python/3.8.1
< Date: Wed, 04 Mar 2020 18:12:28 GMT
```

##### Create a Domain

If the domain already exists, the domain and all sub-elements will be overwritten.  Optionally, a merge process can be implemented.

Method: `POST`
URL: `https://[URL BLOCKING SERVICE FQDN or IP]/admin/domains`

Request Body

```json
{
    "badguys.cisco.com:443": {
        "safe": false,
        "path": {
            "/safe": {
                "safe": true,
                "qs": [
                    {
                        "evil": "1234",
                        "safe": false
                    }
                ]
            }
        }
    }
}
```

HTTP Responses

* HTTP 202 (Accepted): If resource was created.
* HTTP 409 (Conflict): If resource already exists.

Example Response Payload #1

```bash
curl \
  --verbose \
  --header "Content-Type: application/json" \
  --request POST 'http://localhost:8080/admin/domains' \
  --data "$(cat test.json)"

< HTTP/1.0 202 ACCEPTED
< Content-Type: text/html; charset=utf-8
< Content-Length: 14
< Server: Werkzeug/1.0.0 Python/3.8.1
< Date: Wed, 04 Mar 2020 18:18:07 GMT
```

--

## Roadmap

Setting expectations in any project is an important step to define goals and feature completion dates.

Any additional items requested by the scope of work will require additional time to be added to the project budget and delivery timelines.

* On acceptance of the design, the initial project implementation will be delivered within 2 business days.

  * It is expected that the initial design will implement the URL blocking service requests and the URL blocking service management commands.  

* On acceptance of the design, the initial project testing and test plan will be delivered with 2 business days, thereafter.

## Delivery Expectations

The project will be delivered as a Docker container with the necessary operating instructions and scripts to perform tests against each of the service endpoints.
