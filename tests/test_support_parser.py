from forge.analyzer.support import parse_support_metadata


SUPPORT_XML = b"""
<ContentDBInstall VERSION="1.0">
  <Products>
    <Product VALUE="VYK Dystopian Daisy for Genesis 9">
      <StoreID VALUE="DAZ 3D"/>
      <GlobalID VALUE="b877e79e-22a2-431f-813d-0d17a15f4aa7"/>
      <ProductToken VALUE="106273"/>
      <Artists>
        <Artist VALUE="vyktohria"/>
        <Artist VALUE="Websoul"/>
      </Artists>
      <Assets>
        <Asset VALUE="/People/Genesis 9/Characters/Hero.duf">
          <ContentType VALUE="Actor/Character"/>
          <Audience VALUE="Adult"/>
          <Categories>
            <Category VALUE="/Default/Figures/People/Female/Real World"/>
          </Categories>
          <CompatibilityBase VALUE="/Genesis 9/Base"/>
          <Compatibilities>
            <Compatibility VALUE="/Genesis 9/Base"/>
            <Compatibility VALUE="/Genesis 9/Eyes"/>
          </Compatibilities>
          <Userwords>
            <Userword VALUE="hero"/>
          </Userwords>
        </Asset>
      </Assets>
    </Product>
  </Products>
</ContentDBInstall>
"""


def test_parse_support_product_fields() -> None:
    metadata = parse_support_metadata(SUPPORT_XML)

    assert metadata.product_name == "VYK Dystopian Daisy for Genesis 9"
    assert metadata.store_id == "DAZ 3D"
    assert metadata.global_id == "b877e79e-22a2-431f-813d-0d17a15f4aa7"
    assert metadata.product_token == "106273"
    assert metadata.artists == ("vyktohria", "Websoul")


def test_parse_support_asset_rows() -> None:
    metadata = parse_support_metadata(SUPPORT_XML)

    assert len(metadata.assets) == 1
    asset = metadata.assets[0]
    assert asset.path == "/People/Genesis 9/Characters/Hero.duf"
    assert asset.content_type == "Actor/Character"
    assert asset.audience == "Adult"
    assert asset.categories == ("/Default/Figures/People/Female/Real World",)
    assert asset.compatibility_base == "/Genesis 9/Base"
    assert asset.compatibilities == ("/Genesis 9/Base", "/Genesis 9/Eyes")
    assert asset.userwords == ("hero",)