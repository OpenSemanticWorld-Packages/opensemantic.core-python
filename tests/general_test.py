import opensemantic.core


def test_opensemantic():

    # Create an instance of OswBaseModel
    model = opensemantic.core.Entity(
        label=[opensemantic.core.Label(text="Test Entity")],
    )

    # Check if the instance is created successfully
    assert isinstance(
        model, opensemantic.core.Entity
    ), "Failed to create an instance of OswBaseModel"


if __name__ == "__main__":
    test_opensemantic()
    print("All tests passed!")
