from pathlib import Path
import pytest

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from declarative_elements import *


@pytest.fixture(scope="module")
def chrome_driver() -> webdriver.Chrome:
    chrome_options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(executable_path="chromedriver",
                              options=chrome_options)
    yield driver
    driver.quit()


@pytest.fixture(scope="session")
def local_webpage_path() -> str:
    path = Path(__file__).parent / "testpage" / "index.html"
    return f"file://{path.resolve()}"


@pytest.fixture
def driver_on_page(chrome_driver, local_webpage_path) -> WebDriver:
    chrome_driver.get(local_webpage_path)
    return chrome_driver


@pytest.fixture()
def wait_on_page(driver_on_page) -> WebDriverWait:
    return WebDriverWait(driver_on_page, 5)


class DomTreeElementBase(ElementHandle):
    parent = element(..., By.XPATH, "./parent::*")
    children = elements(..., By.XPATH, "./child::*")

    @element(...)
    def relative(self, xpath_axis="descendant", tag="*"):
        return By.XPATH, f"./{xpath_axis}::{tag}"

    @elements(...)
    def relatives(self, xpath_axis="descendant", tag="*"):
        return By.XPATH, f"./{xpath_axis}::{tag}"


def test_basics(wait_on_page: WebDriverWait):
    raw_body = wait_on_page.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    assert isinstance(raw_body, WebElement) and raw_body.tag_name == "body"

    # ElementHandle wraps WebElement or WebDriver and property .element is the wrapee
    body = DomTreeElementBase(raw_body)
    assert body.element == raw_body

    # element(..., *locator) creates descriptor that when called seek web element matching locator
    # using owner_instance.element as an anchor and wraps it into owner class.
    # Instruction to wrap in descriptor's owner class (here DomTreeElementBase)
    # encoded in ... notation
    html = body.parent
    assert isinstance(html, DomTreeElementBase)
    assert html.element.tag_name == "html"

    # elements() is like element(), but search for all elements matching supplied locator
    html_children = html.children
    assert isinstance(html_children, list)
    assert all(isinstance(child, DomTreeElementBase) for child in html_children)
    head, body2 = html_children
    assert head.element.tag_name == "head"

    # two ElementHandles are equal if corresponding .element properties are equal
    # and not equal otherwise
    assert body.element == body2.element
    assert body == body2
    assert body.element != head.element
    assert body != head

    # element() and elements() could also be used to create descriptor from other descriptor
    # such as method, classmethod, staticmethod, property etc.
    # When called it calls underlying descriptor, get returned locator and
    # search for web element[s] as in previous examples
    assert head.relative(xpath_axis="following-sibling") == body
    search_band = body.relatives(tag="table")[0]
    search_band2 = body.children[1].children[0].children[4].children[0]
    assert search_band.element.tag_name == "table"
    assert search_band == search_band2


class Input(ElementHandle):
    @route(...)
    @classmethod
    def found(cls, name: str = None, value: str = None):
        predicates = []
        if name is not None:
            predicates.append(f"@name='{name}'")
        if value is not None:
            predicates.append(f"@value='{value}'")
        predicates = " and ".join(predicates)
        if predicates:
            predicates = f"[{predicates}]"
        return By.XPATH, f".//input{predicates}"

    @routes(...)
    @classmethod
    def found_all_of_type(cls, type_: str = None):
        return By.CSS_SELECTOR, f"input[type='{type_}']"

    @property
    def name(self):
        return self.element.get_attribute("name")

    @property
    def value(self):
        return self.element.get_attribute("value")

    @property
    def type(self):
        return self.element.get_attribute("type")


class SearchBand(ElementHandle):
    found = route(..., By.CSS_SELECTOR, "table[border='0']")
    search_button = element(Input, By.CSS_SELECTOR, "input[type='submit']")
    reset_button = element(By.CSS_SELECTOR, "input[type='reset']")

    @element(Input)
    def get_query_input(self):
        return By.CSS_SELECTOR, "input[name='query']"


SearchBand.reset_button.bind(Input)


def test_callable_based_route_to_self(wait_on_page: WebDriverWait):
    # route() and routes() work similar with element() and elements()
    # with difference they are not returning wrapped elements on call,
    # but callables that return these things when called in they turn.
    # element[s]() descriptors implicitly use owner_instance.element as an
    # anchor from which to search. Aforementioned callables accept anchors explicitly as
    # first and only argument of type WebElement or WebDriver.
    search_button_found = Input.found(value="Search")

    # WebDriverWait.until() accepts exactly such callables
    search_button1 = wait_on_page.until(search_button_found)
    assert isinstance(search_button1, Input)
    assert isinstance(search_button1.element, WebElement)
    assert search_button1.element.tag_name == "input"
    assert search_button1.value == "Search"

    # explicitly pass WebDriver inside callable
    search_button2: Input = search_button_found(wait_on_page._driver)
    assert search_button1 == search_button2
    assert search_button1.element == search_button2.element


def test_locator_based_route_to_self(wait_on_page: WebDriverWait):
    # route() and routes() descriptors could also be defined with
    # static locator - (by.something, selector) pair. Just like element() and elements()
    search_band1 = wait_on_page.until(SearchBand.found)
    assert isinstance(search_band1, SearchBand)
    assert isinstance(search_band1.element, WebElement)
    assert search_band1.element.tag_name == "table"

    search_band2 = SearchBand.found(wait_on_page._driver)
    assert search_band1 == search_band2
    assert search_band1.element == search_band2.element


def test_callable_based_routes_to_self(wait_on_page: WebDriverWait):
    checkboxes_found = Input.found_all_of_type("checkbox")
    checkboxes1 = wait_on_page.until(checkboxes_found)
    assert isinstance(checkboxes1, list)
    assert isinstance(checkboxes1[0], Input)
    assert {box.name for box in checkboxes1} == {
        'showother', 'casesensitive', 'descriptionfield', 'showkeyword', 'urlfield',
        'showdescription', 'titlefield', 'showurl', 'keywordfield'
    }

    checkboxes2 = checkboxes_found(wait_on_page._driver)
    assert checkboxes1 == checkboxes2


def test_locator_based_element_of_nonowner_type(wait_on_page: WebDriverWait):
    # if element[s]() or route[s]() descriptor defined with specific
    # descendant of ElementHandle instead of ... then it returning value
    # wraps in that descendant (here Input)
    # instead of descriptor owner class (here SearchBand)
    search_band: SearchBand = wait_on_page.until(SearchBand.found)
    search_button = search_band.search_button
    assert isinstance(search_button, Input)
    assert search_button.value == "Search"


def test_element_late_binding_to_type(wait_on_page: WebDriverWait):
    # if element[s]() or route[s]() descriptor defined without specific
    # descendant of ElementHandle or ... then it returning value is that descriptor itself
    # before returning value it should be bound to some descendant of ElementHandle with .bind().
    # Such behavior could be of use in case desired descendant not yet exists in scope
    # at the moment of descriptor's instantiation.
    search_band: SearchBand = wait_on_page.until(SearchBand.found)
    assert search_band.reset_button.value == "Reset"


def test_callable_based_element_of_nonowner_type(wait_on_page: WebDriverWait):
    search_band: SearchBand = wait_on_page.until(SearchBand.found)
    query_input = search_band.get_query_input()
    assert isinstance(query_input, Input)
    query_input.element.send_keys("123")
    assert query_input.value == "123"
    search_band.reset_button.element.click()
    assert not query_input.value


def test_route_from_element(wait_on_page: WebDriverWait):
    search_band: SearchBand = wait_on_page.until(SearchBand.found)
    input_within = Input.found()
    query_input = input_within(search_band.element)
    assert search_band.get_query_input() == query_input
