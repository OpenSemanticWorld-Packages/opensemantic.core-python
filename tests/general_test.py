import rdflib


def test_opensemantic():

    import opensemantic.core
    import opensemantic.core.v1

    # Create an instance of OswBaseModel
    model = opensemantic.core.Entity(
        label=[opensemantic.core.Label(text="Test Entity")],
    )

    # Check if the instance is created successfully
    assert isinstance(
        model, opensemantic.core.Entity
    ), "Failed to create an instance of Entity"

    # repeaet for v1
    model_v1 = opensemantic.core.v1.Entity(
        label=[opensemantic.core.v1.Label(text="Test Entity")],
    )
    assert isinstance(
        model_v1, opensemantic.core.v1.Entity
    ), "Failed to create an instance of Entity in v1"


def test_rdf(model_version: str = ""):

    if model_version == "v1":
        import opensemantic.core.v1 as model
    else:
        import opensemantic.core as model

    keyword = model.Keyword(label=[model.Label(text="Test Keyword")])
    item = model.Item(
        label=[model.Label(text="Test Item")],
        description=[model.Description(text="This is a test entity")],
        keywords=[],
    )

    print(item.to_jsonld())

    # load in rdflib Graph

    g = rdflib.Graph()
    g.parse(data=item.to_jsonld(), format="json-ld")
    g.parse(data=keyword.to_jsonld(), format="json-ld")

    # SPARQL query to check if
    # skos:prefLabel == "Test Item"
    # schema:keyword / skos:prefLabel == "Test Keyword"
    res = g.query(
        """
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX schema: <http://schema.org/>
        SELECT ?itemLabel ?keywordLabel WHERE {
            ?item skos:prefLabel ?itemLabel .
            ?item schema:keywords ?keyword .
            ?keyword skos:prefLabel ?keywordLabel .
        }
    """
    )

    assert all(
        str(row.itemLabel) == "Test Item" and str(row.keywordLabel) == "Test Keyword"
        for row in res
    )


if __name__ == "__main__":
    test_opensemantic()
    test_rdf()
    print("All tests passed!")
