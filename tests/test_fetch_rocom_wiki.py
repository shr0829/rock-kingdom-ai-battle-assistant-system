import unittest

from scripts.fetch_rocom_wiki import parse_pets, parse_skills


class FetchRocomWikiTests(unittest.TestCase):
    def test_parse_pet_card(self) -> None:
        page = """
        <div class="divsort" data-param1="最终形态" data-param2="光" data-param4="原始形态" data-param5="原始形态" data-param6="否">
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>NO.001</span></a>
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>迪莫</span></a>
          <img src="pet.png" class="rocom_prop_icon" />
          <img src="light.png" class="rocom_pet_icon" />
        </div>
        """

        pets = parse_pets(page)

        self.assertEqual(len(pets), 1)
        self.assertEqual(pets[0].name, "迪莫")
        self.assertEqual(pets[0].no, "NO.001")
        self.assertEqual(pets[0].primary_attribute, "光")

    def test_parse_skill_card(self) -> None:
        page = """
        <div class="divsort" data-param0="40" data-param1="物攻" data-param2="普通">
          <img src="normal.png" class="rocom_skill_attribute_icon" />
          <a href="/rocom/%E9%A3%9E%E8%B8%A2" title="飞踢"><img src="skill.png" class="rocom_skill_bg_img" /></a>
        </div>
        """

        skills = parse_skills(page)

        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0].name, "飞踢")
        self.assertEqual(skills[0].power, "40")
        self.assertEqual(skills[0].category, "物攻")
        self.assertEqual(skills[0].attribute, "普通")


if __name__ == "__main__":
    unittest.main()
