"""
    flask.ext.restless.search
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    Provides querying, searching, and function evaluation on SQLAlchemy models.

    The most important functions in this module are the :func:`create_query`
    and :func:`search` functions, which create a SQLAlchemy query object and
    execute that query on a given model, respectively.

    :copyright: 2011 by Lincoln de Sousa <lincoln@comum.org>
    :copyright: 2012, 2013, 2014, 2015 Jeffrey Finkelstein
                <jeffrey.finkelstein@gmail.com> and contributors.
    :license: GNU AGPLv3+ or BSD

"""
import inspect

from sqlalchemy import and_
from sqlalchemy import or_
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm.attributes import InstrumentedAttribute

from .helpers import get_related_model
from .helpers import get_related_association_proxy_model
from .helpers import primary_key_names
from .helpers import session_query
from .helpers import string_to_datetime


class ComparisonToNull(Exception):
    pass


def _sub_operator(model, argument, fieldname):
    """Recursively calls :func:`QueryBuilder._create_operation` when argument
    is a dictionary of the form specified in :ref:`search`.

    This function is for use with the ``has`` and ``any`` search operations.

    """
    if isinstance(model, InstrumentedAttribute):
        submodel = model.property.mapper.class_
    elif isinstance(model, AssociationProxy):
        submodel = get_related_association_proxy_model(model)
    else:  # TODO what to do here?
        pass
    if isinstance(argument, dict):
        fieldname = argument['name']
        operator = argument['op']
        argument = argument.get('val')
        relation = None
        if '__' in fieldname:
            fieldname, relation = fieldname.split('__')
        return QueryBuilder._create_operation(submodel, fieldname, operator,
                                              argument, relation)
    # Support legacy has/any with implicit eq operator
    return getattr(submodel, fieldname) == argument


#: The mapping from operator name (as accepted by the search method) to a
#: function which returns the SQLAlchemy expression corresponding to that
#: operator.
#:
#: Each of these functions accepts either one, two, or three arguments. The
#: first argument is the field object on which to apply the operator. The
#: second argument, where it exists, is either the second argument to the
#: operator or a dictionary as described below. The third argument, where it
#: exists, is the name of the field.
#:
#: For functions that accept three arguments, the second argument may be a
#: dictionary containing ``'name'``, ``'op'``, and ``'val'`` mappings so that
#: :func:`QueryBuilder._create_operation` may be applied recursively. For more
#: information and examples, see :ref:`search`.
#:
#: Some operations have multiple names. For example, the equality operation can
#: be described by the strings ``'=='``, ``'eq'``, ``'equals'``, etc.
OPERATORS = {
    # Operators which accept a single argument.
    'is_null': lambda f: f == None,
    'is_not_null': lambda f: f != None,
    # 'desc': lambda f: f.desc,
    # 'asc': lambda f: f.asc,
    # Operators which accept two arguments.
    '==': lambda f, a: f == a,
    'eq': lambda f, a: f == a,
    'equals': lambda f, a: f == a,
    'equal_to': lambda f, a: f == a,
    '!=': lambda f, a: f != a,
    'ne': lambda f, a: f != a,
    'neq': lambda f, a: f != a,
    'not_equal_to': lambda f, a: f != a,
    'does_not_equal': lambda f, a: f != a,
    '>': lambda f, a: f > a,
    'gt': lambda f, a: f > a,
    '<': lambda f, a: f < a,
    'lt': lambda f, a: f < a,
    '>=': lambda f, a: f >= a,
    'ge': lambda f, a: f >= a,
    'gte': lambda f, a: f >= a,
    'geq': lambda f, a: f >= a,
    '<=': lambda f, a: f <= a,
    'le': lambda f, a: f <= a,
    'lte': lambda f, a: f <= a,
    'leq': lambda f, a: f <= a,
    'ilike': lambda f, a: f.ilike(a),
    'like': lambda f, a: f.like(a),
    'in': lambda f, a: f.in_(a),
    'not_in': lambda f, a: ~f.in_(a),
    # Operators which accept three arguments.
    'has': lambda f, a, fn: f.has(_sub_operator(f, a, fn)),
    'any': lambda f, a, fn: f.any(_sub_operator(f, a, fn)),
}


class Filter(object):
    """Represents a filter to apply to a SQL query.

    A filter can be, for example, a comparison operator applied to a field of a
    model and a value or a comparison applied to two fields of the same
    model. For more information on possible filters, see :ref:`search`.

    """

    def __init__(self, fieldname, operator, argument=None, otherfield=None):
        """Instantiates this object with the specified attributes.

        `fieldname` is the name of the field of a model which will be on the
        left side of the operator.

        `operator` is the string representation of an operator to apply. The
        full list of recognized operators can be found at :ref:`search`.

        If `argument` is specified, it is the value to place on the right side
        of the operator. If `otherfield` is specified, that field on the model
        will be placed on the right side of the operator.

        .. admonition:: About `argument` and `otherfield`

           Some operators don't need either argument and some need exactly one.
           However, this constructor will not raise any errors or otherwise
           inform you of which situation you are in; it is basically just a
           named tuple. Calling code must handle errors caused by missing
           required arguments.

        """
        self.fieldname = fieldname
        self.operator = operator
        self.argument = argument
        self.otherfield = otherfield

    def __repr__(self):
        """Returns a string representation of this object."""
        return '<Filter {0} {1} {2}>'.format(self.fieldname, self.operator,
                                             self.argument or self.otherfield)

    @staticmethod
    def from_dictionary(model, dictionary):
        """Returns a new :class:`Filter` object with arguments parsed from
        `dictionary`.

        `dictionary` is a dictionary of the form::

            {'name': 'age', 'op': 'lt', 'val': 20}

        or::

            {'name': 'age', 'op': 'lt', 'other': 'height'}

        where ``dictionary['name']`` is the name of the field of the model on
        which to apply the operator, ``dictionary['op']`` is the name of the
        operator to apply, ``dictionary['val']`` is the value on the right to
        which the operator will be applied, and ``dictionary['other']`` is the
        name of the other field of the model to which the operator will be
        applied.

        'dictionary' may also be an arbitrary Boolean formula consisting of
        dictionaries such as these. For example::

            {'or':
                 [{'and':
                       [dict(name='name', op='like', val='%y%'),
                        dict(name='age', op='ge', val=10)]},
                  dict(name='name', op='eq', val='John')
                  ]
             }

        """
        # If there are no ANDs or ORs, we are in the base case of the
        # recursion.
        if 'or' not in dictionary and 'and' not in dictionary:
            fieldname = dictionary.get('name')
            operator = dictionary.get('op')
            otherfield = dictionary.get('field')
            argument = dictionary.get('val')
            # Need to deal with the special case of converting dates.
            argument = string_to_datetime(model, fieldname, argument)
            return Filter(fieldname, operator, argument, otherfield)
        # For the sake of brevity, rename this method.
        from_dict = Filter.from_dictionary
        # If there is an OR or an AND in the dictionary, recurse on the
        # provided list of filters.
        if 'or' in dictionary:
            subfilters = dictionary.get('or')
            return DisjunctionFilter(*[from_dict(model, filter_)
                                       for filter_ in subfilters])
        if 'and' in dictionary:
            subfilters = dictionary.get('and')
            return ConjunctionFilter(*[from_dict(model, filter_)
                                       for filter_ in subfilters])


class JunctionFilter(Filter):

    def __init__(self, *subfilters):
        self.subfilters = subfilters

    def __iter__(self):
        return iter(self.subfilters)


class ConjunctionFilter(JunctionFilter):
    def __repr__(self):
        return 'and_{0}'.format(tuple(repr(f) for f in self))


class DisjunctionFilter(JunctionFilter):
    def __repr__(self):
        return 'or_{0}'.format(tuple(repr(f) for f in self))


class QueryBuilder(object):
    """Provides a static function for building a SQLAlchemy query object based
    on a :class:`SearchParameters` instance.

    Use the static :meth:`create_query` method to create a SQLAlchemy query on
    a given model.

    """

    @staticmethod
    def _create_operation(model, fieldname, operator, argument, relation=None):
        """Translates an operation described as a string to a valid SQLAlchemy
        query parameter using a field or relation of the specified model.

        More specifically, this translates the string representation of an
        operation, for example ``'gt'``, to an expression corresponding to a
        SQLAlchemy expression, ``field > argument``. The recognized operators
        are given by the keys of :data:`OPERATORS`. For more information on
        recognized search operators, see :ref:`search`.

        If `relation` is not ``None``, the returned search parameter will
        correspond to a search on the field named `fieldname` on the entity
        related to `model` whose name, as a string, is `relation`.

        `model` is an instance of a SQLAlchemy declarative model being
        searched.

        `fieldname` is the name of the field of `model` to which the operation
        will be applied as part of the search. If `relation` is specified, the
        operation will be applied to the field with name `fieldname` on the
        entity related to `model` whose name, as a string, is `relation`.

        `operation` is a string representating the operation which will be
         executed between the field and the argument received. For example,
         ``'gt'``, ``'lt'``, ``'like'``, ``'in'`` etc.

        `argument` is the argument to which to apply the `operator`.

        `relation` is the name of the relationship attribute of `model` to
        which the operation will be applied as part of the search, or ``None``
        if this function should not use a related entity in the search.

        This function raises the following errors:
        * :exc:`KeyError` if the `operator` is unknown (that is, not in
          :data:`OPERATORS`)
        * :exc:`TypeError` if an incorrect number of arguments are provided for
          the operation (for example, if `operation` is `'=='` but no
          `argument` is provided)
        * :exc:`AttributeError` if no column with name `fieldname` or
          `relation` exists on `model`

        """
        # raises KeyError if operator not in OPERATORS
        opfunc = OPERATORS[operator]
        # In Python 3.0 or later, this should be `inspect.getfullargspec`
        # because `inspect.getargspec` is deprecated.
        numargs = len(inspect.getargspec(opfunc).args)
        # raises AttributeError if `fieldname` or `relation` does not exist
        field = getattr(model, relation or fieldname)
        # each of these will raise a TypeError if the wrong number of argments
        # is supplied to `opfunc`.
        if numargs == 1:
            return opfunc(field)
        if argument is None:
            msg = ('To compare a value to NULL, use the is_null/is_not_null '
                   'operators.')
            raise ComparisonToNull(msg)
        if numargs == 2:
            return opfunc(field, argument)
        return opfunc(field, argument, fieldname)

    @staticmethod
    def _create_filter(model, filt):
        """Returns the operation on `model` specified by the provided filter.

        `filt` is an instance of the :class:`Filter` class.

        Raises one of :exc:`AttributeError`, :exc:`KeyError`, or
        :exc:`TypeError` if there is a problem creating the query. See the
        documentation for :func:`_create_operation` for more information.

        """
        # If the filter is not a conjunction or a disjunction, simply proceed
        # as normal.
        if not isinstance(filt, JunctionFilter):
            fname = filt.fieldname
            val = filt.argument
            # get the relationship from the field name, if it exists
            relation = None
            if '__' in fname:
                relation, fname = fname.split('__')
            # get the other field to which to compare, if it exists
            if filt.otherfield:
                val = getattr(model, filt.otherfield)
            # for the sake of brevity...
            create_op = QueryBuilder._create_operation
            return create_op(model, fname, filt.operator, val, relation)
        # Otherwise, if this filter is a conjunction or a disjunction, make
        # sure to apply the appropriate filter operation.
        create_filt = QueryBuilder._create_filter
        if isinstance(filt, ConjunctionFilter):
            return and_(create_filt(model, f) for f in filt)
        return or_(create_filt(model, f) for f in filt)

    @staticmethod
    def create_query(session, model, filters=None, sort=None, group_by=None,
                     _ignore_order_by=False):
        """Builds an SQLAlchemy query instance based on the search parameters
        present in ``search_params``, an instance of :class:`SearchParameters`.

        This method returns a SQLAlchemy query in which all matched instances
        meet the requirements specified in ``search_params``.

        `model` is SQLAlchemy declarative model on which to create a query.

        `search_params` is an instance of :class:`SearchParameters` which
        specify the filters, order, limit, offset, etc. of the query.

        If `_ignore_order_by` is ``True``, no ``order_by`` method will be
        called on the query, regardless of whether the search parameters
        indicate that there should be an ``order_by``. (This is used internally
        by Flask-Restless to work around a limitation in SQLAlchemy.)

        Building the query proceeds in this order:
        1. filtering
        2. ordering
        3. grouping
        3. limiting
        4. offsetting

        Raises one of :exc:`AttributeError`, :exc:`KeyError`, or
        :exc:`TypeError` if there is a problem creating the query. See the
        documentation for :func:`_create_operation` for more information.

        """
        query = session_query(session, model)

        # Filter the query.
        filters = [Filter.from_dictionary(model, f) for f in filters]
        # This function call may raise an exception.
        filters = [QueryBuilder._create_filter(model, f) for f in filters]
        query = query.filter(*filters)

        # Order the query. If no order field is specified, order by primary
        # key.
        if not _ignore_order_by:
            if sort:
                for (symbol, field_name) in sort:
                    direction_name = 'asc' if symbol == '+' else 'desc'
                    if '.' in field_name:
                        field_name, field_name_in_relation = \
                            field_name.split('.')
                        relation_model = get_related_model(model, field_name)
                        field = getattr(relation_model, field_name_in_relation)
                        direction = getattr(field, direction_name)
                        query = query.join(relation_model)
                        query = query.order_by(direction())
                    else:
                        field = getattr(model, field_name)
                        direction = getattr(field, direction_name)
                        query = query.order_by(direction())
            else:
                pks = primary_key_names(model)
                pk_order = (getattr(model, field).asc() for field in pks)
                query = query.order_by(*pk_order)

        # Group the query.
        if group_by:
            for field_name in group_by:
                if '.' in field_name:
                    field_name, field_name_in_relation = field_name.split('.')
                    relation_model = get_related_model(model, field_name)
                    field = getattr(relation_model, field_name_in_relation)
                    query = query.join(relation_model)
                    query = query.group_by(field)
                else:
                    field = getattr(model, field_name)
                    query = query.group_by(field)

        return query


def search(session, model, filters=None, sort=None, group_by=None,
           single=False, _ignore_order_by=False):
    """Performs the search specified by the given parameters on the model
    specified in the constructor of this class.

    This function essentially calls :func:`create_query` to create a query
    which matches the set of all instances of ``model`` which meet the search
    parameters defined in ``search_params``, then returns all results (or just
    one if ``search_params['single'] == True``).

    This function returns a single instance of the model matching the search
    parameters if ``search_params['single']`` is ``True``, or a list of all
    such instances otherwise. If ``search_params['single']`` is ``True``, then
    this method will raise :exc:`sqlalchemy.orm.exc.NoResultFound` if no
    results are found and :exc:`sqlalchemy.orm.exc.MultipleResultsFound` if
    multiple results are found.

    `model` is a SQLAlchemy declarative model class representing the database
    model to query.

    `sort` is a list of two-tuples of the form ``(direction, fieldname)``,
    where ``direction`` is either ``'+'`` or ``'-'`` and ``fieldname`` is a
    string representing an attribute of the model or a dot-separated
    relationship path (for example, ``'owner.name'``).

    `search_params` is a dictionary containing all available search
    parameters. For more information on available search parameters, see
    :ref:`search`. Implementation note: this dictionary will be converted to a
    :class:`SearchParameters` object when the :func:`create_query` function is
    called.

    If `_ignore_order_by` is ``True``, no ``order_by`` method will be called on
    the query, regardless of whether the search parameters indicate that there
    should be an ``order_by``. (This is used internally by Flask-Restless to
    work around a limitation in SQLAlchemy.)

    """
    # # `is_single` is True when 'single' is a key in ``search_params`` and its
    # # corresponding value is anything except those values which evaluate to
    # # False (False, 0, the empty string, the empty list, etc.).
    # is_single = search_params.get('single')
    query = QueryBuilder.create_query(session, model, filters, sort, group_by,
                                      _ignore_order_by)
    if single:
        # may raise NoResultFound or MultipleResultsFound
        return query.one()
    return query
