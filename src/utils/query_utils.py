from pathlib import Path
from jinja2 import Environment, FileSystemLoader


def render_query_template(template_file, input_dict):
    """
    Render an SQL query template with provided input data.

    This function loads an SQL query template file, renders it using the
    provided input dictionary, and returns the rendered query as a string.
    The template rendering is done using Jinja2.

    Parameters
    ----------
    template_file : str
        The path to the SQL query template file.
    input_dict : dict
        A dictionary containing the input data for rendering the template.
        The keys in the dictionary should match the placeholders in the
        template.

    Returns
    -------
    str
        The rendered SQL query as a string.

    Examples
    --------
    >>> template_file = 'path/to/template.sql'
    >>> input_dict = {'date': '2024-06-10'}
    >>> rendered_query = render_query_template(template_file, input_dict)
    >>> print(rendered_query)
    SELECT * FROM rtb_bids
    created_at == '2024-06-10'
    LIMIT 10;
    """
    template_path = Path(template_file)
    template_dir = template_path.parent
    template_filename = template_path.name
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template(template_filename)
    query = template.render(input_dict)
    return query
