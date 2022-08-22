"""Allow slides to be inserted into your documentation.

Inclusion of slides can be switched of by a configuration variable.
The slidelist directive collects all slides of your project and lists them along
with a backlink to the original location.
"""

from typing import Any, Dict, List, Tuple, cast

from docutils import nodes
from docutils.nodes import Element, Node
from docutils.parsers.rst import directives
from docutils.parsers.rst.directives.admonitions import BaseAdmonition

import sphinx
from sphinx import addnodes
from sphinx.application import Sphinx
from sphinx.domains import Domain
from sphinx.environment import BuildEnvironment
from sphinx.errors import NoUri
from sphinx.locale import _, __
from sphinx.util import logging, texescape
from sphinx.util.docutils import SphinxDirective, new_document
from sphinx.util.typing import OptionSpec
from sphinx.writers.html import HTMLTranslator
from sphinx.writers.latex import LaTeXTranslator

import os

logger = logging.getLogger(__name__)


class slide_node(nodes.Admonition, nodes.Element):
    pass


class slidelist(nodes.General, nodes.Element):
    pass


class Slide(BaseAdmonition, SphinxDirective):
    """
    A slide entry, displayed (if configured) in the form of an admonition.
    """

    node_class = slide_node
    has_content = True
    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec: OptionSpec = {
        'class': directives.class_option,
        'name': directives.unchanged,
    }

    def run(self) -> List[Node]:

        title = self.content[0]
        self.content.pop(0)

        if not self.options.get('class'):
            self.options['class'] = ['admonition-slide']

        (slide,) = super().run()  # type: Tuple[Node]
        if isinstance(slide, nodes.system_message):
            return [slide]
        elif isinstance(slide, slide_node):
            slide.insert(0, nodes.title(text=_(title)))
            slide['docname'] = self.env.docname
            self.add_name(slide)
            self.set_source_info(slide)
            self.state.document.note_explicit_target(slide)

            rjslide = '\n'
            rjslide += title
            rjslide += '\n'
            rjslide += "-"*len(title)
            rjslide += '\n'
            for line in self.content:
                rjslide += line
                rjslide += '\n'
            rjslide += '\n'
            slide['rjslide'] = rjslide

            return [slide]
        else:
            raise RuntimeError  # never reached here


class SlideDomain(Domain):
    name = 'slide'
    label = 'slide'

    @property
    def slides(self) -> Dict[str, List[slide_node]]:
        return self.data.setdefault('slides', {})

    def clear_doc(self, docname: str) -> None:
        self.slides.pop(docname, None)

    def merge_domaindata(self, docnames: List[str], otherdata: Dict) -> None:
        for docname in docnames:
            self.slides[docname] = otherdata['slides'][docname]

    def process_doc(self, env: BuildEnvironment, docname: str,
                    document: nodes.document) -> None:
        
        print(docname)
        print(document.__dict__)
        print('***************', env.titles)
        # if env.titles != {}:
        #     print('@@@@@@@@@@@@@@@', env.titles[docname])
        if len(list(document.findall(slide_node))):
            sliname = os.path.join('src',docname + '-slides.rst')
            print("Creating file", sliname)
            with open(sliname, "w") as f:
                f.write(".. Created today \n")
        slides = self.slides.setdefault(docname, [])
        for slide in document.findall(slide_node):
            env.app.emit('slide-defined', slide)
            with open(sliname, "a") as f:
                f.write(slide['rjslide'])
            slides.append(slide)

            if env.config.slide_emit_warnings:
                logger.warning(__("SLIDE entry found: %s"), slide[1].astext(),
                               location=slide)


class SlideList(SphinxDirective):
    """
    A list of all slide entries.
    """

    has_content = False
    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec: OptionSpec = {}

    def run(self) -> List[Node]:
        # Simply insert an empty slidelist node which will be replaced later
        # when process_slide_nodes is called
        return [slidelist('')]


class SlideListProcessor:
    def __init__(self, app: Sphinx, doctree: nodes.document, docname: str) -> None:
        self.builder = app.builder
        self.config = app.config
        self.env = app.env
        self.domain = cast(SlideDomain, app.env.get_domain('slide'))
        self.document = new_document('')

        self.process(doctree, docname)

    def process(self, doctree: nodes.document, docname: str) -> None:
        slides: List[slide_node] = sum(self.domain.slides.values(), [])
        for node in list(doctree.findall(slidelist)):
            if not self.config.slide_include_slides:
                node.parent.remove(node)
                continue

            if node.get('ids'):
                content: List[Element] = [nodes.target()]
            else:
                content = []

            for slide in slides:
                # Create a copy of the slide node
                new_slide = slide.deepcopy()
                new_slide['ids'].clear()

                self.resolve_reference(new_slide, docname)
                content.append(new_slide)

                slide_ref = self.create_slide_reference(slide, docname)
                content.append(slide_ref)

            node.replace_self(content)

    def create_slide_reference(self, slide: slide_node, docname: str) -> nodes.paragraph:
        if self.config.slide_link_only:
            description = _('<<original entry>>')
        else:
            description = (_('(The <<original entry>> is located in %s, line %d.)') %
                           (slide.source, slide.line))

        prefix = description[:description.find('<<')]
        suffix = description[description.find('>>') + 2:]

        para = nodes.paragraph(classes=['slide-source'])
        para += nodes.Text(prefix)

        # Create a reference
        linktext = nodes.emphasis(_('original entry'), _('original entry'))
        reference = nodes.reference('', '', linktext, internal=True)
        try:
            reference['refuri'] = self.builder.get_relative_uri(docname, slide['docname'])
            reference['refuri'] += '#' + slide['ids'][0]
        except NoUri:
            # ignore if no URI can be determined, e.g. for LaTeX output
            pass

        para += reference
        para += nodes.Text(suffix)

        return para

    def resolve_reference(self, slide: slide_node, docname: str) -> None:
        """Resolve references in the slide content."""
        for node in slide.findall(addnodes.pending_xref):
            if 'refdoc' in node:
                node['refdoc'] = docname

        # Note: To resolve references, it is needed to wrap it with document node
        self.document += slide
        self.env.resolve_references(self.document, docname, self.builder)
        self.document.remove(slide)


def visit_slide_node(self: HTMLTranslator, node: slide_node) -> None:
    if self.config.slide_include_slides:
        self.visit_admonition(node)
    else:
        raise nodes.SkipNode


def depart_slide_node(self: HTMLTranslator, node: slide_node) -> None:
    self.depart_admonition(node)


def latex_visit_slide_node(self: LaTeXTranslator, node: slide_node) -> None:
    if self.config.slide_include_slides:
        self.body.append('\n\\begin{sphinxadmonition}{note}{')
        self.body.append(self.hypertarget_to(node))

        title_node = cast(nodes.title, node[0])
        title = texescape.escape(title_node.astext(), self.config.latex_engine)
        self.body.append('%s:}' % title)
        node.pop(0)
    else:
        raise nodes.SkipNode


def latex_depart_slide_node(self: LaTeXTranslator, node: slide_node) -> None:
    self.body.append('\\end{sphinxadmonition}\n')


def setup(app: Sphinx) -> Dict[str, Any]:
    app.add_event('slide-defined')
    app.add_config_value('slide_include_slides', False, 'html')
    app.add_config_value('slide_link_only', False, 'html')
    app.add_config_value('slide_emit_warnings', False, 'html')

    app.add_node(slidelist)
    app.add_node(slide_node,
                 html=(visit_slide_node, depart_slide_node),
                 latex=(latex_visit_slide_node, latex_depart_slide_node),
                 text=(visit_slide_node, depart_slide_node),
                 man=(visit_slide_node, depart_slide_node),
                 texinfo=(visit_slide_node, depart_slide_node))

    app.add_directive('slide', Slide)
    app.add_directive('slidelist', SlideList)
    app.add_domain(SlideDomain)
    app.connect('doctree-resolved', SlideListProcessor)
    return {
        'version': sphinx.__display_version__,
        'env_version': 2,
        'parallel_read_safe': True
    }