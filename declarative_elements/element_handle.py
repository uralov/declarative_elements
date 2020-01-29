"""
TODO Descroib as fuc
TODO Fix typings
"""

from typing import (
    List, Tuple, Callable, Type, Any,
    Union, TypeVar
)
from contextlib import suppress
from abc import ABC, abstractmethod
from functools import partial
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By


T = TypeVar("T")
T1 = TypeVar("T1")
T2 = TypeVar("T2")


def _is_subclass(cls, classinfo) -> bool:
    return isinstance(cls, type) and issubclass(cls, classinfo)


def _compose(f: Callable[..., T1],
             g: Callable[[T1], T2]) -> Callable[..., T2]:
    return lambda *args, **kwargs: g(f(*args, **kwargs))


WebElemSearcheable = Union[WebDriver, WebElement]
SearchResult = Union[T, List[T]]


class ElementHandle:
    def __init__(self, element: WebElement):
        self._element = element

    @property
    def element(self) -> WebElement:
        return self._element

    def __eq__(self, other):
        return self.element == other.element

    def __hash__(self):
        return self.element.__hash__()

    @classmethod
    def wrap(cls, search_result: SearchResult[WebElement]):
        if isinstance(search_result, list):
            return [cls(elem) for elem in search_result]
        return cls(search_result)


class ElementRoute:
    supported_selector_kinds = frozenset(
        v for (k, v) in By.__dict__.items() if not k.startswith("__")
    )

    def __init__(self, by: str, selector: str, find_all=False):
        self.by = by
        self.selector = selector
        self.find_all = find_all
        if self.by not in self.supported_selector_kinds:
            raise ValueError("Selector kind is not supported",
                             self.by, self.supported_selector_kinds)

    def __call__(self, start: WebElemSearcheable) -> SearchResult[WebElement]:
        find = start.find_elements if self.find_all else start.find_element
        return find(self.by, self.selector)


class ClassAttributeDecorator(ABC):
    def __init__(self, class_attribute):
        self.class_attribute = class_attribute

    def __get__(self, owner_instance, owner_type=None):
        gotten_attr = self.class_attribute
        if hasattr(gotten_attr, "__get__"):
            gotten_attr = gotten_attr.__get__(owner_instance, owner_type)
        return self._modify(gotten_attr, owner_instance, owner_type)

    @abstractmethod
    def _modify(self, value, owner_instance, owner_type):
        pass


Locator = Tuple[str, str]
LocatorFactory = Callable[..., Locator]
ElementHandleRoute = Callable[[WebElemSearcheable], SearchResult[ElementHandle]]


class RouteDescriptor(ClassAttributeDecorator):
    def __init__(self,
                 find_all: bool,
                 owner_is_destination: bool,
                 destination: Union[Type[ElementHandle], None],
                 class_attribute):
        super().__init__(class_attribute)
        self.find_all = find_all
        self.owner_is_destination = owner_is_destination
        self.destination = None
        if destination is not None:
            self.bind(destination)

    @staticmethod
    def check_is_element_handle(destination: Type[ElementHandle]):
        if not _is_subclass(destination, ElementHandle):
            raise TypeError(
                f"Not a valid destination or owner type, subclass of {ElementHandle} required",
                destination)

    def bind(self, destination: Type[ElementHandle]):
        self.check_is_element_handle(destination)
        self.destination = destination
        return self

    def __set_name__(self, owner_type, attr_name) -> None:
        if self.owner_is_destination:
            # TODO think about binding to caller owner_type instead of initial owner_type
            self.bind(owner_type)
        else:
            self.check_is_element_handle(owner_type)

    def __get__(self, owner_instance: ElementHandle, owner_type: Type[ElementHandle] = None):
        if self.destination is None:
            return self
        return super().__get__(owner_instance, owner_type)

    def _modify(self, value, owner_instance, owner_type):
        transform_locator = self._locator_transformation(owner_instance, owner_type)

        if isinstance(value, Callable):
            return self._transform_factory(value, transform_locator)

        if isinstance(value, tuple):
            return transform_locator(value)

        raise TypeError(f"Wrapped attribute type is different from {Locator} or {LocatorFactory}",
                        value)

    def _locator_transformation(
        self, owner_instance, owner_type
    ) -> Callable[[Locator], ElementHandleRoute]:
        return self._locator_to_element_handle_route

    def _transform_factory(self, locator_factory: LocatorFactory, transformation):
        return _compose(locator_factory, transformation)

    def _locator_to_element_handle_route(self, locator: Locator) -> ElementHandleRoute:
        delegete = _compose(self._locator_to_element_route,
                            self._element_route_to_element_handle_route)
        return delegete(locator)

    def _element_route_to_element_handle_route(
        self, element_route: ElementRoute
    ) -> ElementHandleRoute:
        return _compose(element_route, self.destination.wrap)

    def _locator_to_element_route(self, locator: Locator) -> ElementRoute:
        return ElementRoute(*locator, self.find_all)


ElementHandleFactory = Callable[[], ElementHandle]


class ElementHandleFactoryDescriptor(RouteDescriptor):

    def __get__(self, owner_instance: ElementHandle, owner_type: Type[ElementHandle] = None):
        if owner_type is None:
            return self
        return super().__get__(owner_instance, owner_type)

    def _locator_transformation(self, owner_instance: ElementHandle,
                                owner_type) -> Callable[[Locator], ElementHandleFactory]:
        return partial(self._locator_to_element_handle_factory, owner_instance.element)

    def _locator_to_element_handle_factory(self, start: WebElement,
                                           locator: Locator) -> ElementHandleFactory:
        route = super()._locator_to_element_handle_route(locator)
        return partial(route, start)


class ElementHandleDescriptor(ElementHandleFactoryDescriptor):

    def _locator_transformation(self, owner_instance: ElementHandle,
                                owner_type) -> Callable[[Locator], ElementHandle]:
        return partial(self._locator_to_element_handle, owner_instance.element)

    def _locator_to_element_handle(self, start: WebElement, locator: Locator) -> ElementHandle:
        route = super()._locator_to_element_handle_route(locator)
        return route(start)


def _parse_destination_mark(destination_mark: Union[Type[ElementHandle], type(Ellipsis)], *args):
    if destination_mark is ...:
        return True, None, args

    try:
        RouteDescriptor.check_is_element_handle(destination_mark)
    except TypeError:
        return False, None, (destination_mark,) + args

    return False, destination_mark, args


def _parse_wrapee_attribute(*args):
    with suppress(ValueError, TypeError):
        by, selector, *args = args
        if by not in ElementRoute.supported_selector_kinds:
            raise ValueError
        return (by, selector), args

    attr, *args = args
    return attr, args


def _descriptor_factory(descriptor_type: Union[RouteDescriptor, ElementHandleDescriptor],
                        find_all: bool,
                        *args: Union[Type[ElementHandle], type(Ellipsis), Any]):
    subfactory = partial(descriptor_type, find_all)

    owner_is_destination, destination, args = _parse_destination_mark(*args)
    subfactory = partial(subfactory, owner_is_destination, destination)

    if not args:
        return subfactory

    attribute, args = _parse_wrapee_attribute(*args)
    if not args:
        return subfactory(attribute)

    raise ValueError("Too many values passed")


route = partial(_descriptor_factory, RouteDescriptor, False)
routes = partial(_descriptor_factory, RouteDescriptor, True)
element = partial(_descriptor_factory, ElementHandleDescriptor, False)
elements = partial(_descriptor_factory, ElementHandleDescriptor, True)
