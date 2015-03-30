# -*- encoding: utf-8 -*-
"""
    tests.test_creating
    ~~~~~~~~~~~~~~~~~~~

    Provides tests for creating resources from endpoints generated by
    Flask-Restless.

    This module includes tests for additional functionality that is not already
    tested by :mod:`test_jsonapi`, the module that guarantees Flask-Restless
    meets the minimum requirements of the JSON API specification.

    :copyright: 2015 Jeffrey Finkelstein <jeffrey.finkelstein@gmail.com> and
                contributors.
    :license: GNU AGPLv3+ or BSD

"""
from __future__ import division
from datetime import time
from datetime import timedelta
from datetime import datetime

import dateutil
try:
    from flask.ext.sqlalchemy import SQLAlchemy
except:
    has_flask_sqlalchemy = False
else:
    has_flask_sqlalchemy = True
from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Interval
from sqlalchemy import Time
from sqlalchemy import Unicode
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship

from flask.ext.restless import APIManager
from flask.ext.restless import CONTENT_TYPE
from flask.ext.restless import DeserializationException
from flask.ext.restless import simple_serialize

from .helpers import BetterJSONEncoder as JSONEncoder
from .helpers import dumps
from .helpers import DatabaseTestBase
from .helpers import loads
from .helpers import FlaskTestBase
from .helpers import ManagerTestBase
from .helpers import MSIE8_UA
from .helpers import MSIE9_UA
from .helpers import skip_unless
from .helpers import unregister_fsa_session_signals


class TestCreating(ManagerTestBase):
    """Tests for creating resources."""

    def setUp(self):
        """Creates the database, the :class:`~flask.Flask` object, the
        :class:`~flask_restless.manager.APIManager` for that application, and
        creates the ReSTful API endpoints for the :class:`TestSupport.Person`
        and :class:`TestSupport.Article` models.

        """
        super(TestCreating, self).setUp()

        class Article(self.Base):
            __tablename__ = 'article'
            id = Column(Integer, primary_key=True)
            date_created = Column(Date)
            author_id = Column(Integer, ForeignKey('person.id'))
            author = relationship('Person')

        class Person(self.Base):
            __tablename__ = 'person'
            id = Column(Integer, primary_key=True)
            age = Column(Integer)
            name = Column(Unicode, unique=True)
            birth_datetime = Column(DateTime, nullable=True)
            bedtime = Column(Time)
            hangtime = Column(Interval)
            articles = relationship('Article')

            @hybrid_property
            def is_minor(self):
                if hasattr(self, 'age'):
                    if self.age is None:
                        return None
                    return self.age < 18
                return None

        class Tag(self.Base):
            __tablename__ = 'tag'
            name = Column(Unicode, primary_key=True)
            # TODO this dummy column is required to create an API for this
            # object.
            id = Column(Integer)

        self.Article = Article
        self.Person = Person
        self.Tag = Tag
        self.Base.metadata.create_all()
        self.manager.create_api(Person, methods=['POST'])
        self.manager.create_api(Article, methods=['POST'])
        self.manager.create_api(Tag, methods=['POST'])

    def test_related_resource_url_forbidden(self):
        """Tests that :http:method:`post` requests to a related resource URL
        are forbidden.

        """
        person = self.Person(id=1)
        article = self.Article(id=1)
        self.session.add_all([person, article])
        self.session.commit()
        data = dict(data=dict(type='article', id=1))
        response = self.app.post('/api/person/1/articles', data=dumps(data))
        assert response.status_code == 405
        # TODO check error message here
        assert person.articles == []

    def test_deserializing_time(self):
        """Test for deserializing a JSON representation of a time field."""
        bedtime = datetime.now().time()
        data = dict(data=dict(type='person', bedtime=bedtime))
        data = dumps(data, cls=JSONEncoder)
        response = self.app.post('/api/person', data=data)
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['bedtime'] == bedtime.isoformat()

    def test_deserializing_date(self):
        """Test for deserializing a JSON representation of a date field."""
        date_created = datetime.now().date()
        data = dict(data=dict(type='article', date_created=date_created))
        data = dumps(data, cls=JSONEncoder)
        response = self.app.post('/api/article', data=data)
        assert response.status_code == 201
        document = loads(response.data)
        article = document['data']
        assert article['date_created'] == date_created.isoformat()

    def test_deserializing_datetime(self):
        """Test for deserializing a JSON representation of a date field."""
        birth_datetime = datetime.now()
        data = dict(data=dict(type='person', birth_datetime=birth_datetime))
        data = dumps(data, cls=JSONEncoder)
        response = self.app.post('/api/person', data=data)
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['birth_datetime'] == birth_datetime.isoformat()

    def test_correct_content_type(self):
        """Tests that the server responds with :http:status:`201` if the
        request has the correct JSON API content type.

        """
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data),
                                 content_type=CONTENT_TYPE)
        assert response.status_code == 201
        assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_no_content_type(self):
        """Tests that the server responds with :http:status:`415` if the
        request has no content type.

        """
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data),
                                 content_type=None)
        assert response.status_code == 415
        assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_wrong_content_type(self):
        """Tests that the server responds with :http:status:`415` if the
        request has the wrong content type.

        """
        data = dict(data=dict(type='person'))
        bad_content_types = ('application/json', 'application/javascript')
        for content_type in bad_content_types:
            response = self.app.post('/api/person', data=dumps(data),
                                     content_type=content_type)
            # TODO Why are there two copies of the Content-Type header here?
            assert response.status_code == 415
            assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_msie8(self):
        """Tests for compatibility with Microsoft Internet Explorer 8.

        According to issue #267, making requests using JavaScript from MSIE8
        does not allow changing the content type of the request (it is always
        ``text/html``). Therefore Flask-Restless should ignore the content type
        when a request is coming from this client.

        """
        headers = {'User-Agent': MSIE8_UA}
        content_type = 'text/html'
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data),
                                 headers=headers, content_type=content_type)
        assert response.status_code == 201

    def test_msie9(self):
        """Tests for compatibility with Microsoft Internet Explorer 9.

        According to issue #267, making requests using JavaScript from MSIE9
        does not allow changing the content type of the request (it is always
        ``text/html``). Therefore Flask-Restless should ignore the content type
        when a request is coming from this client.

        """
        headers = {'User-Agent': MSIE9_UA}
        content_type = 'text/html'
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data),
                                 headers=headers, content_type=content_type)
        assert response.status_code == 201

    def test_no_data(self):
        """Tests that a request with no data yields an error response."""
        response = self.app.post('/api/person')
        assert response.status_code == 400
        # TODO check the error message here

    def test_invalid_json(self):
        """Tests that a request with an invalid JSON causes an error response.

        """
        response = self.app.post('/api/person', data='Invalid JSON string')
        assert response.status_code == 400
        # TODO check the error message here

    def test_conflicting_attributes(self):
        """Tests that an attempt to create a resource with a non-unique
        attribute value where uniqueness is required causes a
        :http:status:`409` response.

        """
        person = self.Person(name='foo')
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', name='foo'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 409  # Conflict
        # TODO check error message here

    def test_rollback_on_integrity_error(self):
        """Tests that an integrity error in the database causes a session
        rollback, and that the server can still process requests correctly
        after this rollback.

        """
        person = self.Person(name='foo')
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', name='foo'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 409  # Conflict
        assert self.session.is_active, 'Session is in `partial rollback` state'
        person = dict(data=dict(type='person', name='bar'))
        response = self.app.post('/api/person', data=dumps(person))
        assert response.status_code == 201

    def test_nonexistent_attribute(self):
        """Tests that the server rejects an attempt to create a resource with
        an attribute that does not exist in the resource.

        """
        data = dict(data=dict(type='person', bogus=0))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 400
        # TODO check error message here

    def test_hybrid_property(self):
        """Tests that an attempt to set a read-only hybrid property causes an
        error.

        See issue #171.

        """
        data = dict(data=dict(type='person', is_minor=True))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 400
        # TODO check error message here

    def test_nullable_datetime(self):
        """Tests for creating a model with a nullable datetime field.

        For more information, see issue #91.

        """
        data = dict(data=dict(type='person', birth_datetime=None))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['birth_datetime'] is None

    def test_empty_date(self):
        """Tests that attempting to assign an empty date string to a date field
        actually assigns a value of ``None``.

        For more information, see issue #91.

        """
        data = dict(data=dict(type='person', birth_datetime=''))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['birth_datetime'] is None

    def test_current_timestamp(self):
        """Tests that the string ``'CURRENT_TIMESTAMP'`` gets converted into a
        datetime object when making a request to set a date or time field.

        """
        data = dict(data=dict(type='person',
                              birth_datetime='CURRENT_TIMESTAMP'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['birth_datetime'] is not None
        birth_datetime = dateutil.parser.parse(person['birth_datetime'])
        diff = datetime.utcnow() - birth_datetime
        # Check that the total number of seconds from the server creating the
        # Person object to (about) now is not more than about a minute.
        assert diff.days == 0
        assert (diff.seconds + diff.microseconds / 1000000) < 3600

    def test_timedelta(self):
        """Tests for creating an object with a timedelta attribute."""
        data = dict(data=dict(type='person', hangtime=300))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['hangtime'] == 300

    def test_to_many(self):
        """Tests the creation of a model with a to-many relation."""
        article1 = self.Article(id=1)
        article2 = self.Article(id=2)
        self.session.add_all([article1, article2])
        self.session.commit()
        data = {'data':
                    {'type': 'person',
                     'links':
                         {'articles':
                              [{'type': 'article', 'id': '1'},
                               {'type': 'article', 'id': '2'}]
                          }
                     }
                }
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        articles = person['links']['articles']['linkage']
        assert ['1', '2'] == sorted(article['id'] for article in articles)
        assert all(article['type'] == 'article' for article in articles)

    def test_to_one(self):
        """Tests the creation of a model with a to-one relation."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        data = {'data':
                    {'type': 'article',
                     'links':
                         {'author': {'type': 'person', 'id': '1'}}
                     }
                }
        response = self.app.post('/api/article', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        article = document['data']
        person = article['links']['author']['linkage']
        assert person['type'] == 'person'
        assert person['id'] == '1'

    def test_unicode_primary_key(self):
        """Test for creating a resource with a unicode primary key."""
        data = dict(data=dict(type='tag', name=u'Юникод'))
        response = self.app.post('/api/tag', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        tag = document['data']
        assert tag['name'] == u'Юникод'

    def test_primary_key_as_id(self):
        """Tests the even if a primary key is not named ``id``, it still
        appears in an ``id`` key in the response.

        """
        data = dict(data=dict(type='tag', name=u'foo'))
        response = self.app.post('/api/tag', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        tag = document['data']
        assert tag['id'] == u'foo'

    # TODO Not supported right now.
    #
    # def test_treat_as_id(self):
    #     """Tests for specifying one attribute in a compound primary key by
    #     which to create a resource.

    #     """
    #     manager = APIManager(self.flaskapp, session=self.session)
    #     manager.create_api(self.User, primary_key='email')
    #     data = dict(data=dict(type='user', id=1))
    #     response = self.app.post('/api/user', data=dumps(data))
    #     document = loads(response.data)
    #     user = document['data']
    #     assert user['id'] == '1'
    #     assert user['type'] == 'user'
    #     assert user['email'] == 'foo'

    def test_collection_name(self):
        """Tests for creating a resource with an alternate collection name."""
        self.manager.create_api(self.Person, methods=['POST'],
                                collection_name='people')
        data = dict(data=dict(type='people'))
        response = self.app.post('/api/people', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['type'] == 'people'

    # TODO This behavior is no longer supported
    #
    # def test_nested_relations(self):
    #     # Test with nested objects
    #     data = {'name': 'Rodriguez', 'age': 70,
    #             'computers': [{'name': 'iMac', 'vendor': 'Apple',
    #                            'programs': [{'program': {'name': 'iPhoto'}}]}]}
    #     response = self.app.post('/api/person', data=dumps(data))
    #     assert 201 == response.status_code
    #     response = self.app.get('/api/computer/2/programs')
    #     programs = loads(response.data)['objects']
    #     assert programs[0]['program']['name'] == 'iPhoto'

    def test_custom_serialization(self):
        """Tests for custom deserialization."""
        temp = []

        def serializer(instance):
            result = simple_serialize(instance)
            result['foo'] = temp.pop()
            return result

        def deserializer(data):
            temp.append(data.pop('foo'))
            instance = self.Person(**data)
            return instance

        # POST will deserialize once and serialize once
        self.manager.create_api(self.Person, methods=['POST'],
                                url_prefix='/api2',
                                serializer=serializer,
                                deserializer=deserializer)
        data = dict(data=dict(type='person', foo='bar'))
        response = self.app.post('/api2/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['foo'] == 'bar'

    def test_deserialization_exception(self):
        """Tests that exceptions are caught when a custom deserialization
        method raises an exception.

        """

        def deserializer(*args, **kw):
            raise DeserializationException

        self.manager.create_api(self.Person, methods=['POST'],
                                url_prefix='/api2',
                                deserializer=deserializer)
        data = dict(data=dict(type='person'))
        response = self.app.post('/api2/person', data=dumps(data))
        assert response.status_code == 400
        # TODO check error message here


class TestProcessors(ManagerTestBase):
    """Tests for pre- and postprocessors."""

    def setUp(self):
        super(TestProcessors, self).setUp()

        class Person(self.Base):
            __tablename__ = 'person'
            id = Column(Integer, primary_key=True)
            name = Column(Unicode)

        self.Person = Person
        self.Base.metadata.create_all()

    def test_preprocessor(self):
        """Tests :http:method:`post` requests with a preprocessor function."""

        def set_name(data=None, **kw):
            """Sets the name attribute of the incoming data object, regardless
            of the value requested by the client.

            """
            if data is not None:
                data['data']['name'] = 'bar'

        preprocessors = dict(POST=[set_name])
        self.manager.create_api(self.Person, methods=['POST'],
                                preprocessors=preprocessors)
        data = dict(data=dict(type='person', name='foo'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['name'] == 'bar'


class TestAssociationProxy(ManagerTestBase):
    """Tests for creating an object with a relationship using an association
    proxy.

    """

    def setUp(self):
        """Creates the database, the :class:`~flask.Flask` object, the
        :class:`~flask.ext.restless.manager.APIManager` for that application,
        and creates the ReSTful API endpoints for the models used in the test
        methods.

        """
        super(TestAssociationProxy, self).setUp()

        class Article(self.Base):
            __tablename__ = 'article'
            id = Column(Integer, primary_key=True)
            tags = association_proxy('articletags', 'tag',
                                     creator=lambda tag: ArticleTag(tag=tag))

        class ArticleTag(self.Base):
            __tablename__ = 'articletag'
            article_id = Column(Integer, ForeignKey('article.id'),
                                primary_key=True)
            article = relationship(Article, backref=backref('articletags'))
            tag_id = Column(Integer, ForeignKey('tag.id'), primary_key=True)
            tag = relationship('Tag')
            # TODO this dummy column is required to create an API for this
            # object.
            id = Column(Integer)

        class Tag(self.Base):
            __tablename__ = 'tag'
            id = Column(Integer, primary_key=True)
            name = Column(Unicode)

        self.Tag = Tag
        self.Base.metadata.create_all()
        self.manager.create_api(Article, methods=['POST'])
        # HACK Need to create APIs for these other models because otherwise
        # we're not able to create the link URLs to them.
        #
        # TODO Fix this by simply not creating links to related models for
        # which no API has been made.
        self.manager.create_api(Tag)
        self.manager.create_api(ArticleTag)

    def test_create(self):
        """Test for creating a new instance of the database model that has a
        many-to-many relation that uses an association object to allow extra
        information to be stored on the association table.

        """
        tag1 = self.Tag(id=1)
        tag2 = self.Tag(id=2)
        self.session.add_all([tag1, tag2])
        self.session.commit()
        data = {'data':
                    {'type': 'article',
                     'links':
                         {'tags':
                              [{'type': 'tag', 'id': '1'},
                               {'type': 'tag', 'id': '2'}]
                          }
                     }
                }
        response = self.app.post('/api/article', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        article = document['data']
        links = article['links']
        tags = links['tags']['linkage']
        assert ['1', '2'] == sorted(tag['id'] for tag in tags)

    def test_scalar(self):
        """Tests for creating a resource with an association proxy to scalars
        as a list attribute instead of a link object.

        """
        tag1 = self.Tag(name='foo')
        tag2 = self.Tag(name='bar')
        self.session.add_all([tag1, tag2])
        self.session.commit()
        data = dict(data=dict(type='article', tag_names=['foo', 'bar']))
        response = self.app.post('/api/article', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        article = document['data']
        assert ['foo', 'bar'] == article['tag_names']

    def test_dictionary_collection(self):
        """Tests for creating a resource with a dictionary based collection via
        an association proxy.

        """
        assert False, 'Not implemented'


@skip_unless(has_flask_sqlalchemy, 'Flask-SQLAlchemy not found.')
class TestFlaskSqlalchemy(FlaskTestBase):
    """Tests for creating resources defined as Flask-SQLAlchemy models instead
    of pure SQLAlchemy models.

    """

    def setUp(self):
        """Creates the Flask-SQLAlchemy database and models."""
        super(TestFlaskSqlalchemy, self).setUp()
        self.db = SQLAlchemy(self.flaskapp)

        class Person(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)

        self.Person = Person
        self.db.create_all()
        self.manager = APIManager(self.flaskapp, flask_sqlalchemy_db=self.db)
        self.manager.create_api(self.Person, methods=['POST'])

    def tearDown(self):
        """Drops all tables and unregisters Flask-SQLAlchemy session signals.

        """
        self.db.drop_all()
        unregister_fsa_session_signals()

    def test_create(self):
        """Tests for creating a resource."""
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        # TODO To make this test more robust, should query for person objects.
        assert person['id'] == '1'
        assert person['type'] == 'person'
