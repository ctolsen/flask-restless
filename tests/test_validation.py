"""
    tests.test_validation
    ~~~~~~~~~~~~~~~~~~~~~

    Provides unit tests for SQLAlchemy models which have some validation
    functionality and therefore raise validation errors when requests are made
    to write to the database.

    Validation is not provided by Flask-Restless itself, but it must capture
    validation errors and return them to the client.

    :copyright: 2012, 2013, 2014, 2015 Jeffrey Finkelstein
                <jeffrey.finkelstein@gmail.com> and contributors.
    :license: GNU AGPLv3+ or BSD

"""
import sys

from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import Unicode
from sqlalchemy.orm import validates

# for SAValidation package on pypi.python.org
try:
    import savalidation as _sav
    import savalidation.validators as sav
except:
    has_savalidation = False
else:
    sav_version = tuple(int(n) for n in _sav.VERSION.split('.'))
    has_savalidation = True

from .helpers import dumps
from .helpers import loads
from .helpers import ManagerTestBase
from .helpers import skip_unless


class TestSimpleValidation(ManagerTestBase):
    """Tests for validation errors raised by the SQLAlchemy's simple built-in
    validation.

    For more information about this functionality, see the documentation for
    :func:`sqlalchemy.orm.validates`.

    """

    def setUp(self):
        """Create APIs for the validated models."""
        super(TestSimpleValidation, self).setUp()

        class CoolValidationError(Exception):
            pass

        class Person(self.Base):
            __tablename__ = 'person'
            id = Column(Integer, primary_key=True)
            age = Column(Integer, nullable=False)

            @validates('age')
            def validate_age(self, key, number):
                if not 0 <= number <= 150:
                    exception = CoolValidationError()
                    exception.errors = dict(age='Must be between 0 and 150')
                    raise exception
                return number

        self.Person = Person
        self.Base.metadata.create_all()
        self.manager.create_api(Person, methods=['POST', 'PATCH'],
                                validation_exceptions=[CoolValidationError])

    def test_create_valid(self):
        """Tests that an attempt to create a valid resource yields no error
        response.

        """
        data = dict(data=dict(type='person', age=1))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['age'] == 1

    def test_create_invalid(self):
        """Tests that an attempt to create an invalid resource yields an error
        response.

        """
        data = dict(data=dict(type='person', age=-1))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 400
        document = loads(response.data)
        errors = document['errors']
        error = errors[0]
        assert 'validation' in error['title'].lower()
        assert 'must be between' in error['detail'].lower()
        # Check that the person was not created.
        assert self.session.query(self.Person).count() == 0

    def test_update_valid(self):
        """Tests that an attempt to update a resource with valid data yields no
        error response.

        """
        person = self.Person(id=1, age=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', age=2))
        response = self.app.patch('/api/person/1', data=dumps(data))
        print(response.data)
        assert response.status_code == 204
        assert person.age == 2

    def test_update_invalid(self):
        """Tests that an attempt to update a resource with invalid data yields
        an error response.

        """
        person = self.Person(id=1, age=1)
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', age=-1))
        response = self.app.patch('/api/person/1', data=dumps(data))
        assert response.status_code == 400
        document = loads(response.data)
        errors = document['errors']
        error = errors[0]
        assert 'validation' in error['title'].lower()
        assert 'must be between' in error['detail'].lower()
        # Check that the person was not updated.
        assert person.age == 1


@skip_unless(has_savalidation and sav_version >= (0, 2) and
             sys.version < (3, 0, 0), 'savalidation not found.')
class TestSAValidation(ManagerTestBase):
    """Tests for validation errors raised by the ``savalidation`` package. For
    more information about this package, see `its PyPI page
    <http://pypi.python.org/pypi/SAValidation>`_.

    """

    def setUp(self):
        """Create APIs for the validated models."""
        super(TestSAValidation, self).setUp()

        class Person(self.Base, _sav.ValidationMixin):
            __tablename__ = 'person'
            id = Column(Integer, primary_key=True)
            email = Column(Unicode)

            sav.validates_presence_of('email')
            sav.validates_email('email')

        self.Person = Person
        self.Base.metadata.create_all()
        exceptions = [_sav.ValidationError]
        self.manager.create_api(Person, methods=['POST', 'PATCH'],
                                validation_exceptions=exceptions)

    def test_create_valid(self):
        """Tests that an attempt to create a valid resource yields no error
        response.

        """
        data = dict(data=dict(type='person', email=u'example@example.com'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 201
        document = loads(response.data)
        person = document['data']
        assert person['email'] == u'example@example.com'

    def test_create_absent(self):
        """Tests that an attempt to create a resource with a missing required
        attribute yields an error response.

        """
        data = dict(data=dict(type='person'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 400
        document = loads(response.data)
        errors = document['errors']
        error = errors[0]
        assert 'validation' in error['title'].lower()
        assert 'email' in error['detail'].lower()
        # Check that the person was not created.
        assert self.session.query(self.Person).count() == 0

    def test_create_invalid(self):
        """Tests that an attempt to create an invalid resource yields an error
        response.

        """
        data = dict(data=dict(type='person', email='bogus'))
        response = self.app.post('/api/person', data=dumps(data))
        assert response.status_code == 400
        document = loads(response.data)
        errors = document['errors']
        error = errors[0]
        assert 'validation' in error['title'].lower()
        assert 'email' in error['detail'].lower()
        # Check that the person was not created.
        assert self.session.query(self.Person).count() == 0

    def test_update_valid(self):
        """Tests that an attempt to update a resource with valid data yields no
        error response.

        """
        person = self.Person(id=1, email='example@example.com')
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', email='foo@example.com'))
        response = self.app.patch('/api/person/1', data=dumps(data))
        assert response.status_code == 204
        assert person.email == u'foo@example.com'

    def test_update_invalid(self):
        """Tests that an attempt to update a resource with invalid data yields
        an error response.

        """
        person = self.Person(id=1, email='example@example.com')
        self.session.add(person)
        self.session.commit()
        data = dict(data=dict(type='person', id='1', email='bogus'))
        response = self.app.patch('/api/person/1', data=dumps(data))
        assert response.status_code == 400
        document = loads(response.data)
        errors = document['errors']
        error = errors[0]
        assert 'validation' in error['title'].lower()
        assert 'email' in error['detail'].lower()
        # Check that the person was not updated.
        assert person.email == u'example@example.com'
