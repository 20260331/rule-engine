:mod:`engine`
=============

.. module:: rule_engine.engine
   :synopsis:

This module contains the primary externally facing API for the package.

Functions
---------

.. autofunction:: resolve_attribute

.. autofunction:: resolve_item

.. autofunction:: type_resolver_from_dataclass

.. autofunction:: type_resolver_from_dict

.. autofunction:: type_resolver_from_sqlalchemy

Classes
-------

.. autoclass:: AccessPath
   :members:
   :special-members: __init__, __str__

.. autoclass:: AccessStep
   :members:

.. autoclass:: SymbolAccess
   :members:
   :special-members: __init__

.. autoclass:: AttributeAccess
   :members:
   :special-members: __init__

.. autoclass:: ItemAccess
   :members:
   :special-members: __init__

.. autoclass:: SliceAccess
   :members:
   :special-members: __init__

.. autoclass:: CallAccess
   :members:
   :special-members: __init__

.. autoclass:: AccessPolicy
   :members:

.. autoclass:: WhitelistAccessPolicy
   :members:
   :special-members: __init__

.. autodata:: ANY

.. autoclass:: Context
   :members:
   :show-inheritance:
   :special-members: __init__
   :undoc-members:

.. autoclass:: Rule
   :members:
   :show-inheritance:
   :special-members: __init__
   :undoc-members:
