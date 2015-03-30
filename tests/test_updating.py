"""
    tests.test_updating
    ~~~~~~~~~~~~~~~~~~~

    Provides tests for updating resources from endpoints generated by
    Flask-Restless.

    This module includes tests for additional functionality that is not already
    tested by :mod:`test_jsonapi`, the module that guarantees Flask-Restless
    meets the minimum requirements of the JSON API specification.

    :copyright: 2015 Jeffrey Finkelstein <jeffrey.finkelstein@gmail.com> and
                contributors.
    :license: GNU AGPLv3+ or BSD

"""
from __future__ import division

from datetime import datetime
from datetime import time
try:
    from flask.ext.sqlalchemy import SQLAlchemy
except ImportError:
    has_flask_sqlalchemy = False
else:
    has_flask_sqlalchemy = True

from sqlalchemy import Column
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import Time
from sqlalchemy import Unicode
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import backref
from sqlalchemy.orm import relationship
from sqlalchemy.orm.collections import attribute_mapped_collection as amc

from flask.ext.restless import APIManager
from flask.ext.restless import CONTENT_TYPE
from flask.ext.restless import ProcessingException

from .helpers import BetterJSONEncoder as JSONEncoder
from .helpers import DatabaseTestBase
from .helpers import dumps
from .helpers import FlaskTestBase
from .helpers import loads
from .helpers import MSIE8_UA
from .helpers import MSIE9_UA
from .helpers import ManagerTestBase
from .helpers import skip
from .helpers import skip_unless
from .helpers import unregister_fsa_session_signals


class TestUpdating(ManagerTestBase):
    """Tests for updating resources."""

    def setUp(self):
        """Creates the database, the :class:`~flask.Flask` object, the
        :class:`~flask_restless.manager.APIManager` for that application, and
        creates the ReSTful API endpoints for the :class:`TestSupport.Person`
        and :class:`TestSupport.Article` models.

        """
        super(TestUpdating, self).setUp()

        class Article(self.Base):
            __tablename__ = 'article'
            id = Column(Integer, primary_key=True)
            author = relationship('Person')
            author_id = Column(Integer, ForeignKey('person.id'))

        class Person(self.Base):
            __tablename__ = 'person'
            id = Column(Integer, primary_key=True)
            name = Column(Unicode, unique=True)
            bedtime = Column(Time)
            date_created = Column(Date)
            birth_datetime = Column(DateTime)

        # This example comes from the SQLAlchemy documentation.
        #
        # The SQLAlchemy documentation is licensed under the MIT license.
        class Interval(self.Base):
            __tablename__ = 'interval'
            id = Column(Integer, primary_key=True)
            start = Column(Integer, nullable=False)
            end = Column(Integer, nullable=False)

            @hybrid_property
            def length(self):
                return self.end - self.start

            @length.setter
            def length(self, value):
                self.end = self.start + value

            @hybrid_property
            def radius(self):
                return self.length / 2

            @radius.expression
            def radius(cls):
                return cls.length / 2

        self.Article = Article
        self.Interval = Interval
        self.Person = Person
        self.Base.metadata.create_all()
        self.manager.create_api(Article, methods=['PUT'])
        self.manager.create_api(Interval, methods=['PUT'])
        self.manager.create_api(Person, methods=['PUT'])

    def test_related_resource_url_forbidden(self):
        """Tests that :http:method:`put` requests to a related resource URL
        are forbidden.

        """
        article = self.Article(id=1)
        person = self.Person(id=1)
        self.session.add_all([article, person])
        self.session.commit()
        data = dict(data=dict(type='person', id=1))
        response = self.app.put('/api/article/1/author', data=dumps(data))
        assert response.status_code == 405
        # TODO check error message here
        assert article.author == None

    def test_deserializing_time(self):
        """Test for deserializing a JSON representation of a time field."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        bedtime = datetime.now().time()
        data = dict(data=dict(type='person', id='1', bedtime=bedtime))
        # Python's built-in JSON encoder doesn't serialize date/time objects by
        # default.
        data = dumps(data, cls=JSONEncoder)
        response = self.app.put('/api/person/1', data=data)
        assert response.status_code == 204
        assert person.bedtime == bedtime

    def test_deserializing_date(self):
        """Test for deserializing a JSON representation of a date field."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        today = datetime.now().date()
        data = dict(data=dict(type='person', id='1', date_created=today))
        # Python's built-in JSON encoder doesn't serialize date/time objects by
        # default.
        data = dumps(data, cls=JSONEncoder)
        response = self.app.put('/api/person/1', data=data)
        assert response.status_code == 204
        assert person.date_created == today

    def test_deserializing_datetime(self):
        """Test for deserializing a JSON representation of a date field."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        now = datetime.now()
        data = dict(data=dict(type='person', id='1', birth_datetime=now))
        # Python's built-in JSON encoder doesn't serialize date/time objects by
        # default.
        data = dumps(data, cls=JSONEncoder)
        response = self.app.put('/api/person/1', data=data)
        assert response.status_code == 204
        assert person.birth_datetime == now

    def test_correct_content_type(self):
        """Tests that the server responds with :http:status:`201` if the
        request has the correct JSON API content type.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1'))
        response = self.app.put('/api/person/1', data=dumps(data),
                                content_type=CONTENT_TYPE)
        assert response.status_code == 204
        assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_no_content_type(self):
        """Tests that the server responds with :http:status:`415` if the
        request has no content type.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1'))
        response = self.app.put('/api/person/1', data=dumps(data),
                                content_type=None)
        assert response.status_code == 415
        assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_wrong_content_type(self):
        """Tests that the server responds with :http:status:`415` if the
        request has the wrong content type.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1'))
        bad_content_types = ('application/json', 'application/javascript')
        for content_type in bad_content_types:
            response = self.app.put('/api/person/1', data=dumps(data),
                                    content_type=content_type)
            assert response.status_code == 415
            assert response.headers['Content-Type'] == CONTENT_TYPE

    def test_msie8(self):
        """Tests for compatibility with Microsoft Internet Explorer 8.

        According to issue #267, making requests using JavaScript from MSIE8
        does not allow changing the content type of the request (it is always
        ``text/html``). Therefore Flask-Restless should ignore the content type
        when a request is coming from this client.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        headers = {'User-Agent': MSIE8_UA}
        content_type = 'text/html'
        data = dict(data=dict(type='person', id='1'))
        response = self.app.put('/api/person/1', data=dumps(data),
                                headers=headers, content_type=content_type)
        assert response.status_code == 204

    def test_msie9(self):
        """Tests for compatibility with Microsoft Internet Explorer 9.

        According to issue #267, making requests using JavaScript from MSIE9
        does not allow changing the content type of the request (it is always
        ``text/html``). Therefore Flask-Restless should ignore the content type
        when a request is coming from this client.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        headers = {'User-Agent': MSIE9_UA}
        content_type = 'text/html'
        data = dict(data=dict(type='person', id='1'))
        response = self.app.put('/api/person/1', data=dumps(data),
                                headers=headers, content_type=content_type)
        assert response.status_code == 204

    def test_rollback_on_integrity_error(self):
        """Tests that an integrity error in the database causes a session
        rollback, and that the server can still process requests correctly
        after this rollback.

        """
        person1 = self.Person(id=1, name='foo')
        person2 = self.Person(id=2, name='bar')
        self.session.add_all([person1, person2])
        self.session.commit()
        data = dict(data=dict(type='person', id='2', name='foo'))
        response = self.app.put('/api/person/2', data=dumps(data))
        assert response.status_code == 409  # Conflict
        assert self.session.is_active, 'Session is in `partial rollback` state'
        person = dict(data=dict(type='person', id='2', name='baz'))
        response = self.app.put('/api/person/2', data=dumps(person))
        assert response.status_code == 204
        assert person2.name == 'baz'

    def test_empty_request(self):
        """Test for making a :http:method:`put` request with no data."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        response = self.app.put('/api/person/1')
        assert response.status_code == 400
        # TODO check the error message here

    def test_empty_string(self):
        """Test for making a :http:method:`put` request with an empty string,
        which is invalid JSON.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        response = self.app.put('/api/person/1', data='')
        assert response.status_code == 400
        # TODO check the error message here

    def test_invalid_json(self):
        """Tests that a request with invalid JSON yields an error response."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        response = self.app.put('/api/person/1', data='Invalid JSON string')
        assert response.status_code == 400
        # TODO check error message here

    def test_nonexistent_attribute(self):
        """Tests that attempting to make a :http:method:`put` request on an
        attribute that does not exist on the specified model yields an error
        response.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', bogus=0))
        response = self.app.put('/api/person/1', data=dumps(data))
        assert 400 == response.status_code

    def test_read_only_hybrid_property(self):
        """Tests that an attempt to set a read-only hybrid property causes an
        error.

        For more information, see issue #171.

        """
        interval = self.Interval(id=1, start=5, end=10)
        self.session.add(interval)
        self.session.commit()
        data = dict(data=dict(type='interval', id='1', radius=1))
        response = self.app.put('/api/interval/1', data=dumps(data))
        assert response.status_code == 400
        # TODO check error message here

    def test_set_hybrid_property(self):
        """Tests that a hybrid property can be correctly set by a client."""
        interval = self.Interval(id=1, start=5, end=10)
        self.session.add(interval)
        self.session.commit()
        data = dict(data=dict(type='interval', id='1', length=4))
        response = self.app.put('/api/interval/1', data=dumps(data))
        assert response.status_code == 204
        assert interval.start == 5
        assert interval.end == 9
        assert interval.radius == 2

    def test_collection_name(self):
        """Tests for updating a resource with an alternate collection name."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        self.manager.create_api(self.Person, methods=['PUT'],
                                collection_name='people')
        data = dict(data=dict(type='people', id='1', name='foo'))
        response = self.app.put('/api/people/1', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'foo'

    def test_different_endpoints(self):
        """Tests for updating the same resource from different endpoints."""
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()
        self.manager.create_api(self.Person, methods=['PUT'],
                                url_prefix='/api2')
        data = dict(data=dict(type='person', id='1', name='foo'))
        response = self.app.put('/api/person/1', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'foo'
        data = dict(data=dict(type='person', id='1', name='bar'))
        response = self.app.put('/api2/person/1', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'bar'

    # TODO This is not required by JSON API, and it was a little bit flimsy
    # anyway.
    #
    # def test_patch_update_relations(self):
    #     """Test for posting a new model and simultaneously adding related
    #     instances *and* updating information on those instances.

    #     For more information see issue #164.

    #     """
    #     # First, create a new computer object with an empty `name` field and a
    #     # new person with no related computers.
    #     response = self.app.post('/api/computer', data=dumps({}))
    #     assert 201 == response.status_code
    #     response = self.app.post('/api/person', data=dumps({}))
    #     assert 201 == response.status_code
    #     # Second, patch the person by setting its list of related computer
    #     # instances to include the previously created computer, *and*
    #     # simultaneously update the `name` attribute of that computer.
    #     data = dict(computers=[dict(id=1, name='foo')])
    #     response = self.app.patch('/api/person/1', data=dumps(data))
    #     assert 200 == response.status_code
    #     # Check that the computer now has its `name` field set.
    #     response = self.app.get('/api/computer/1')
    #     assert 200 == response.status_code
    #     assert 'foo' == loads(response.data)['name']
    #     # Add a new computer by patching person
    #     data = {'computers': [{'id': 1},
    #                           {'name': 'iMac', 'vendor': 'Apple',
    #                            'programs': [{'program': {'name': 'iPhoto'}}]}]}
    #     response = self.app.patch('/api/person/1', data=dumps(data))
    #     assert 200 == response.status_code
    #     response = self.app.get('/api/computer/2/programs')
    #     programs = loads(response.data)['objects']
    #     assert programs[0]['program']['name'] == 'iPhoto'
    #     # Add a program to the computer through the person
    #     data = {'computers': [{'id': 1},
    #                           {'id': 2,
    #                            'programs': [{'program_id': 1},
    #                                         {'program': {'name': 'iMovie'}}]}]}
    #     response = self.app.patch('/api/person/1', data=dumps(data))
    #     assert 200 == response.status_code
    #     response = self.app.get('/api/computer/2/programs')
    #     programs = loads(response.data)['objects']
    #     assert programs[1]['program']['name'] == 'iMovie'

    # TODO this is not required by the JSON API spec.
    #
    # def test_put_same_as_patch(self):
    #     """Tests that :http:method:`put` requests are the same as
    #     :http:method:`patch` requests.

    #     """
    #     # recreate the api to allow patch many at /api/v2/person
    #     self.manager.create_api(self.Person, methods=['GET', 'POST', 'PUT'],
    #                             allow_patch_many=True, url_prefix='/api/v2')

    #     # Creating some people
    #     self.app.post('/api/v2/person',
    #                   data=dumps({'name': u'Lincoln', 'age': 23}))
    #     self.app.post('/api/v2/person',
    #                   data=dumps({'name': u'Lucy', 'age': 23}))
    #     self.app.post('/api/v2/person',
    #                   data=dumps({'name': u'Mary', 'age': 25}))

    #     # change a single entry
    #     resp = self.app.put('/api/v2/person/1', data=dumps({'age': 24}))
    #     assert resp.status_code == 200

    #     resp = self.app.get('/api/v2/person/1')
    #     assert resp.status_code == 200
    #     assert loads(resp.data)['age'] == 24

    #     # Changing the birth date field of the entire collection
    #     day, month, year = 15, 9, 1986
    #     birth_date = date(year, month, day).strftime('%d/%m/%Y')  # iso8601
    #     form = {'birth_date': birth_date}
    #     self.app.put('/api/v2/person', data=dumps(form))

    #     # Finally, testing if the change was made
    #     response = self.app.get('/api/v2/person')
    #     loaded = loads(response.data)['objects']
    #     for i in loaded:
    #         expected = '{0:4d}-{1:02d}-{2:02d}'.format(year, month, day)
    #         assert i['birth_date'] == expected


    # TODO no longer supported
    #
    # def test_patch_autodelete_submodel(self):
    #     """Tests the automatic deletion of entries marked with the
    #     ``__delete__`` flag on an update operation.

    #     It also tests adding an already created instance as a related item.

    #     """
    #     # Creating all rows needed in our test
    #     person_data = {'name': u'Lincoln', 'age': 23}
    #     resp = self.app.post('/api/person', data=dumps(person_data))
    #     assert resp.status_code == 201
    #     comp_data = {'name': u'lixeiro', 'vendor': u'Lemote'}
    #     resp = self.app.post('/api/computer', data=dumps(comp_data))
    #     assert resp.status_code == 201

    #     # updating person to add the computer
    #     update_data = {'computers': {'add': [{'id': 1}]}}
    #     self.app.patch('/api/person/1', data=dumps(update_data))

    #     # Making sure that everything worked properly
    #     resp = self.app.get('/api/person/1')
    #     assert resp.status_code == 200
    #     loaded = loads(resp.data)
    #     assert len(loaded['computers']) == 1
    #     assert loaded['computers'][0]['name'] == u'lixeiro'

    #     # Now, let's remove it and delete it
    #     update2_data = {
    #         'computers': {
    #             'remove': [
    #                 {'id': 1, '__delete__': True},
    #             ],
    #         },
    #     }
    #     resp = self.app.patch('/api/person/1', data=dumps(update2_data))
    #     assert resp.status_code == 200

    #     # Testing to make sure it was removed from the related field
    #     resp = self.app.get('/api/person/1')
    #     assert resp.status_code == 200
    #     loaded = loads(resp.data)
    #     assert len(loaded['computers']) == 0

    #     # Making sure it was removed from the database
    #     resp = self.app.get('/api/computer/1')
    #     assert resp.status_code == 404


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

    def test_change_id(self):
        """Tests that a return value from a preprocessor overrides the ID of
        the resource to fetch as given in the request URL.

        """
        person = self.Person(id=1)
        self.session.add(person)
        self.session.commit()

        def increment_id(instance_id=None, **kw):
            if instance_id is None:
                raise ProcessingException(code=400)
            return str(int(instance_id) + 1)

        preprocessors = dict(PUT_RESOURCE=[increment_id])
        self.manager.create_api(self.Person, methods=['PUT'],
                                preprocessors=preprocessors)
        data = dict(data=dict(type='person', id='1', name='foo'))
        response = self.app.put('/api/person/0', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'foo'

    def test_single_resource_processing_exception(self):
        """Tests for a preprocessor that raises a :exc:`ProcessingException`
        when updating a single resource.

        """
        person = self.Person(id=1, name='foo')
        self.session.add(person)
        self.session.commit()

        def forbidden(**kw):
            raise ProcessingException(code=403, description='forbidden')

        preprocessors = dict(PUT_RESOURCE=[forbidden])
        self.manager.create_api(self.Person, methods=['PUT'],
                                preprocessors=preprocessors)
        data = dict(data=dict(type='person', id='1', name='bar'))
        response = self.app.put('/api/person/1', data=dumps(data))
        assert response.status_code == 403
        document = loads(response.data)
        errors = document['errors']
        assert len(errors) == 1
        error = errors[0]
        assert 'forbidden' == error['detail']
        assert person.name == 'foo'

    def test_single_resource(self):
        """Tests :http:method:`put` requests for a single resource with a
        preprocessor function.

        """
        person = self.Person(id=1, name='foo')
        self.session.add(person)
        self.session.commit()

        def set_name(data=None, **kw):
            """Sets the name attribute of the incoming data object, regardless
            of the value requested by the client.

            """
            if data is not None:
                data['data']['name'] = 'bar'

        preprocessors = dict(PUT_RESOURCE=[set_name])
        self.manager.create_api(self.Person, methods=['PUT'],
                                preprocessors=preprocessors)
        data = dict(data=dict(type='person', id='1', name='baz'))
        response = self.app.put('/api/person/1', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'bar'


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

        # The code for the following three classes comes from the SQLAlchemy
        # documentation
        # http://docs.sqlalchemy.org/en/rel_0_9/orm/extensions/associationproxy.html#proxying-to-dictionary-based-collections
        usercreator = lambda k, v: UserKeyword(special_key=k, keyword=v)

        class User(self.Base):
            __tablename__ = 'user'
            id = Column(Integer, primary_key=True)
            keywords = association_proxy('user_keywords', 'keyword',
                                         creator=usercreator)

        # user_keywords = backref('user_keywords',
        #                         collection_class=amc('special_key'),
        #                         cascade='all, delete-orphan')
        user_keywords = backref('user_keywords',
                                collection_class=amc('special_key'))

        class UserKeyword(self.Base):
            __tablename__ = 'user_keyword'
            special_key = Column(Unicode)
            user_id = Column(Integer, ForeignKey('user.id'), primary_key=True)
            user = relationship(User, backref=user_keywords)
            keyword_id = Column(Integer, ForeignKey('keyword.id'),
                                primary_key=True)
            keyword = relationship('Keyword')
            # TODO this dummy column is required to create an API for this
            # object.
            id = Column(Integer)

        class Keyword(self.Base):
            __tablename__ = 'keyword'
            id = Column(Integer, primary_key=True)
            keyword = Column(Unicode)

        self.Article = Article
        self.Tag = Tag
        self.Base.metadata.create_all()
        self.manager.create_api(Article, methods=['PUT'])
        self.manager.create_api(User, methods=['PUT'])
        # HACK Need to create APIs for these other models because otherwise
        # we're not able to create the link URLs to them.
        #
        # TODO Fix this by simply not creating links to related models for
        # which no API has been made.
        self.manager.create_api(Tag)
        self.manager.create_api(ArticleTag)
        self.manager.create_api(UserKeyword)
        self.manager.create_api(Keyword)

    def test_update(self):
        """Test for updating a model with a many-to-many relation that uses an
        association object to allow extra data to be stored in the association
        table.

        For more info, see issue #166.

        """
        article = self.Article(id=1)
        tag1 = self.Tag(id=1)
        tag2 = self.Tag(id=2)
        self.session.add_all([article, tag1, tag2])
        self.session.commit()
        self.manager.create_api(self.Article, methods=['PUT'],
                                url_prefix='/api2',
                                allow_to_many_replacement=True)
        data = {'data':
                    {'type': 'article',
                     'id': '1',
                     'links':
                         {'tags':
                              [{'type': 'tag', 'id': '1'},
                               {'type': 'tag', 'id': '2'}]
                          }
                     }
                }
        response = self.app.put('/api2/article/1', data=dumps(data))
        assert response.status_code == 204
        assert set(article.tags) == set((tag1, tag2))

    def test_scalar(self):
        """Tests for updating an association proxy to scalars as a list
        attribute instead of a link object.

        """
        article = self.Article(id=1)
        tag1 = self.Tag(name='foo')
        tag2 = self.Tag(name='bar')
        article.tags = [tag1, tag2]
        self.session.add_all([article, tag1, tag2])
        self.session.commit()
        tag_names = ['foo', 'bar']
        data = dict(data=dict(type='article', id='1', tag_names=tag_names))
        response = self.app.put('/api/article/1', data=dumps(data))
        assert response.status_code == 204
        assert ['foo', 'bar'] == article.tag_names

    def test_dictionary_collection(self):
        """Tests for updating a dictionary based collection."""
        assert False, 'Not implemented'

    # # TODO This test should be modified to make a PATCH request on a
    # # relationship URL.
    #
    # def test_patch_remove_m2m(self):
    #     """Test for removing a relation on a model that uses an association
    #     object to allow extra data to be stored in the helper table.

    #     For more information, see issue #166.

    #     """
    #     response = self.app.post('/api/computer', data=dumps({}))
    #     assert 201 == response.status_code
    #     vim = self.Program(name=u'Vim')
    #     emacs = self.Program(name=u'Emacs')
    #     self.session.add_all([vim, emacs])
    #     self.session.commit()
    #     data = {
    #         'programs': [
    #             {
    #                 'program_id': 1,
    #                 'licensed': False
    #             },
    #             {
    #                 'program_id': 2,
    #                 'licensed': True
    #             }
    #         ]
    #     }
    #     response = self.app.patch('/api/computer/1', data=dumps(data))
    #     computer = loads(response.data)
    #     assert 200 == response.status_code
    #     vim_relation = {
    #         'computer_id': 1,
    #         'program_id': 1,
    #         'licensed': False
    #     }
    #     emacs_relation = {
    #         'computer_id': 1,
    #         'program_id': 2,
    #         'licensed': True
    #     }
    #     assert vim_relation in computer['programs']
    #     assert emacs_relation in computer['programs']
    #     data = {
    #         'programs': {
    #             'remove': [{'program_id': 1}]
    #         }
    #     }
    #     response = self.app.patch('/api/computer/1', data=dumps(data))
    #     computer = loads(response.data)
    #     assert 200 == response.status_code
    #     assert vim_relation not in computer['programs']
    #     assert emacs_relation in computer['programs']


@skip_unless(has_flask_sqlalchemy, 'Flask-SQLAlchemy not found.')
class TestFlaskSqlalchemy(FlaskTestBase):
    """Tests for updating resources defined as Flask-SQLAlchemy models instead
    of pure SQLAlchemy models.

    """

    def setUp(self):
        """Creates the Flask-SQLAlchemy database and models."""
        super(TestFlaskSqlalchemy, self).setUp()
        # HACK During testing, we don't want the session to expire, so that we
        # can access attributes of model instances *after* a request has been
        # made (that is, after Flask-Restless does its work and commits the
        # session).
        session_options = dict(expire_on_commit=False)
        self.db = SQLAlchemy(self.flaskapp, session_options=session_options)
        self.session = self.db.session

        class Person(self.db.Model):
            id = self.db.Column(self.db.Integer, primary_key=True)
            name = self.db.Column(self.db.Unicode)

        self.Person = Person
        self.db.create_all()
        self.manager = APIManager(self.flaskapp, flask_sqlalchemy_db=self.db)
        self.manager.create_api(self.Person, methods=['PUT'])

    def tearDown(self):
        """Drops all tables and unregisters Flask-SQLAlchemy session signals.

        """
        self.db.drop_all()
        unregister_fsa_session_signals()

    def test_create(self):
        """Tests for creating a resource."""
        person = self.Person(id=1, name='foo')
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', name='bar'))
        response = self.app.put('/api/person/1', data=dumps(data))
        assert response.status_code == 204
        assert person.name == 'bar'
