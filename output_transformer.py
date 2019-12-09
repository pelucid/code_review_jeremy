import datetime

from api.formatting import beautify, helper_map, ranges
from api.database import MySQL


class OutputTransformer(object):
    def __init__(self):
        self.db = MySQL(schema='api_data')

    def transform(self, results, endpoint=None):
        old_keys = [
            'name',
            'num_empl'
        ]

        new_keys = [
            'legal_name',
            'employee_range'
        ]

        for result in results:
            # Copy values we want to return both formatted and unformatted.
            for new, old in zip(new_keys, old_keys):
                result[new] = result.get(old, None)

            result.update(_beautify_doc(result, helper_map.company))

            result['score'] = self.db.get_score(result['id'])


            if 'addresses' in result:
                result['addresses'] = _beautify_addresses(result['addresses'])

            if 'shareholders' in result:
                result['shareholders'] = _beautify_people(result['shareholders'])

            if 'contacts' in result:
                result['contacts'] = _beautify_people(result['contacts'])
                result['contacts'] = _order_contacts(result['contacts'])

            if 'incorp_date' in result and result["incorp_date"]:
                result['incorp_date'] = _beautify_incorp_date(
                    result['incorp_date'])

            if 'credit' in result:
                result['credit'] = _beautify_monetary_values(
                    result['credit'], helper_map.monetary_fields['credit'])

            if 'financials' in result:
                financials = filter(lambda x: x['turnover'], result['financials'])
                if not financials:
                    latest_rev = 0
                else:
                    latest_rev = max(financials,
                                     key=lambda x: x["account_date"] if x["account_date"]
                                                                     else datetime.datetime.min)
                result["last_revenue"] = latest_rev
                result["last_revenue_range"] = ranges.revenue_range(latest_rev)
                result["last_revenue_headline"] = ranges.revenue_range(latest_rev, infix=' to ')
                result['financials'] = _beautify_monetary_values(
                    result['financials'], helper_map.monetary_fields['financials'])

            if 'family' in result:
                result.update(_beautify_family(result['family']))
                del result['family']

            if isinstance(result.get('website'), dict):
                result['website'] = _beautify_website(result['website'].get('website'))

        return results


def _beautify_doc(doc, helpers):
    """Beautify a result document with a collection of helper functions.

    Arguments:
        doc      Document (dict) to beautify
        helpers  Helper functions to apply (in dict using doc structure)
    """

    pretty = {}

    for key, value in doc.items():
        if key in helpers:
            if isinstance(helpers[key], dict):
                # Supposed to be called recursively (dict in dict).
                if isinstance(value, dict):
                    # Good to go.
                    pretty[key] = _beautify_doc(value, helpers[key])
                else:
                    # Missing data in doc, so just copy whatever's there.
                    pretty[key] = value
            else:
                # Just a value; apply helper
                pretty[key] = helpers[key](value)
        else:
            # No helper, so just copy.
            pretty[key] = value

    return pretty


def _beautify_people(docs):
    """Beautify contacts.
    Arguments:
        docs    Contacts (list of dicts) to beautify
    """
    # Given current code, boolean would turn to "Yes" but perhaps not even used?
    for doc in docs:
        for key in ['first_name', 'last_name', 'name', 'title']:
            if key in doc:
                doc[key] = beautify.pretty_text(doc[key])

        if doc.get('role'):
            doc['role'] = beautify.title_or_upper_director_role(doc['role'])

        if doc.get('types'):
            doc['types'] = beautify.pretty_contact_types(doc['types'])

    return docs


def _beautify_addresses(docs):
    """Beautify the trading addresses in a document.

    Arguments:
        docs     Addresses (list of dicts) to beautify

    TODO: (sam) Needs tests
    """

    for doc in docs:
        doc['postcode'] = beautify.postcode(doc.get('postcode', None))

        is_registered = doc.get('is_registered')

        # Only retain the registered address for the download configuration,
        # other addresses need only be beautified
        vals = []

        keys = [
            'address_line_1',
            'address_line_2',
            'address_line_3',
            'address_line_4',
            'department_name',
            'building',
            'po_box',
            'street_address',
            'locality',
            'town',
            'county']

        for key in keys:

            if key in doc:  # Add the value to the beautified string
                vals.append(doc.get(key))

                if not is_registered:
                    # Only retain registered addresses in the JSON
                    doc.pop(key)

        doc['address'] = beautify.addresses(doc['postcode'], *vals)
        doc['is_registered'] = beautify.boolean(doc.get('is_registered', None))
        doc.pop('uid', None)

    return docs


def _beautify_monetary_values(docs, keys):
    """Beautify monetary values.

    Arguments:
        docs    List of documents whose monetary values will be beautified
        keys    List of keys in a document to beautify
    """

    for doc in docs:
        for key in keys:
            if key in doc:
                doc[key] = beautify.money(doc[key])

    return docs


def _beautify_incorp_date(text):
    """Beautify incorporation dates.

    Arguments:
        doc: Company's 'incorp_date' field"""

    try:
        parsed_date = datetime.datetime.strptime(text, "%Y-%m-%d")
        incorp_date = parsed_date.strftime("%d %b %Y")
    except Exception:
        incorp_date = "?"

    return incorp_date


def _beautify_website(url):
    """Add www if the url doesn't have a subdomain."""
    if url is None:
        return None

    url = "".join(url.split()).lower()
    sub, domain, tld, pages = url_extract.url_extract(url)

    if tld is None or domain is None:
        return None

    sub = sub if sub is not None else "www"

    cleaned_url = "{}.{}.{}".format(sub, domain, tld)
    if pages is not None:
        cleaned_url += "/" + pages
    return cleaned_url


def _beautify_family(docs):
    """Beautify family (company group) labels
    Arguments:
        docs    List of documents
    """

    parent_name_map = {'United Kingdom': 'No UK Parent'}

    doc = dict()
    doc['uk_top_parent_cid'] = None
    doc['uk_top_parent_name'] = 'None'
    doc['parent_cid'] = None
    doc['parent_name'] = 'None'
    doc['subsidiaries'] = []

    if not docs:
        return doc

    for d in docs:
        if d['label'] == 'uk_top_parent':
            doc['uk_top_parent_cid'] = d['cid']
            doc['uk_top_parent_name'] = d['name']
        elif d['label'] == 'parent':
            doc['parent_name'] = parent_name_map.get(d['name'], d['name'])
            doc['parent_cid'] = d['cid']
        else:
            doc['subsidiaries'].append(d)

    return doc

def _order_contacts(contacts_array):
    """Return a contact array ordered by type.
    - Primary contact first (if exists)
    - Financial controller second (if exists)
    - Marketing controller third (if exists)
    - The rest of the order does not matter.
    """

    # Filter contacts by type first
    contact_priority = ["Primary Contact", "Financial Controller", "Marketing Controller"]
    sorted_contacts = []
    for c_type in contact_priority:
        contact = filter(lambda c, t=c_type: t in c["types"], contacts_array)
        i = contacts_array.index(contact[0]) if contact else None
        if isinstance(i, int):
            sorted_contacts.append(contacts_array.pop(i))
    # Add the rest of the contacts to the end.
    sorted_contacts += contacts_array
    return sorted_contacts