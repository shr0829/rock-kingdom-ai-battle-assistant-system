import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.fetch_rocom_wiki import (
    parse_pet_detail,
    parse_pets,
    parse_skill_detail,
    parse_skills,
    serialize_entry,
    write_csv,
)


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
        self.assertEqual(pets[0].race_stats, {})
        self.assertEqual(pets[0].characteristics, [])
        self.assertEqual(pets[0].skills, [])

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
        self.assertEqual(skills[0].energy, "")
        self.assertEqual(skills[0].effect, "")

    def test_parse_pet_detail_race_and_skill_tabs(self) -> None:
        page = """
        <div class="rocom_sprite_info_title font-mainfeiziti">
          <p><img alt="图标 宠物 资质 种族.png" />种族值</p><p>582</p>
        </div>
        <div class="rocom_sprite_info_qualification font-fzltyjt">
          <li><p class="rocom_sprite_info_qualification_name">生命</p><p class="rocom_sprite_info_qualification_value">120</p></li>
          <li><p class="rocom_sprite_info_qualification_name">物攻</p><p class="rocom_sprite_info_qualification_value">80</p></li>
        </div>
        <div class="rocom_sprite_info_characteristic_content">
          <div class="rocom_sprite_info_characteristic_content_icon"><p><img alt="最好的伙伴" /></p></div>
          <p class="rocom_sprite_info_characteristic_title font-mainfeiziti">最好的伙伴</p>
          <p class="rocom_sprite_info_characteristic_text font-fzltyjt">造成克制伤害后，获得攻防速+20%，并回复2能量。</p>
        </div>
        <div class="tabbertab" title="精灵技能">
          <div class="rocom_sprite_skill_box">
            <div class="rocom_sprite_skill_level font-mainfeiziti">LV1&nbsp;</div>
            <div class="rocom_sprite_skill_img">
              <img alt="图标 宠物 属性 普通.png" class="rocom_sprite_skill_attr" />
              <a href="/rocom/%E7%8C%9B%E7%83%88%E6%92%9E%E5%87%BB" title="猛烈撞击"><img src="skill.png" /></a>
            </div>
            <div class="rocom_sprite_skillName font-mainfeiziti color_reuse">猛烈撞击</div>
            <div class="rocom_sprite_skillDamage font-mainfeiziti"><img alt="star" />1</div>
            <div class="rocom_sprite_skillType font-fzltyjt"><img alt="type" />物攻</div>
            <div class="rocom_sprite_skill_power font-mainfeiziti">65</div>
            <div class="rocom_sprite_skillContent font-fzltyjt">✦对敌方精灵造成物理伤害。</div>
          </div>
        </div>
        <div class="tabbertab" title="血脉技能">
          <div class="rocom_sprite_skill_box">
            <div class="rocom_sprite_skillName font-mainfeiziti color_reuse">星星撞击</div>
          </div>
        </div>
        <div class="tabbertab" title="可学技能石">
          <div class="rocom_sprite_skill_box">
            <div class="rocom_sprite_skillName font-mainfeiziti color_reuse">超导</div>
          </div>
        </div>
        """

        details = parse_pet_detail(page)

        self.assertEqual(details["race_total"], "582")
        self.assertEqual(details["race_stats"], {"生命": "120", "物攻": "80"})
        self.assertEqual(details["characteristics"], [{"name": "最好的伙伴", "effect": "造成克制伤害后，获得攻防速+20%，并回复2能量。"}])
        self.assertEqual(details["skills"][0]["name"], "猛烈撞击")
        self.assertEqual(details["skills"][0]["attribute"], "普通")
        self.assertEqual(details["skills"][0]["category"], "物攻")
        self.assertEqual(details["skills"][0]["power"], "65")
        self.assertEqual(details["bloodline_skills"][0]["name"], "星星撞击")
        self.assertEqual(details["learnable_skills"][0]["name"], "超导")

    def test_parse_skill_detail_core_fields(self) -> None:
        page = """
        <div class="rocom_skill_template_skillAttribute"><img alt="图标 宠物 属性 普通.png" />普通系</div>
        <div class="rocom_skill_template_skillConsume">
          <div class="rocom_skill_template_skillConsume_box"><span>0</span></div><span>耗能</span>
        </div>
        <div class="rocom_skill_template_skillSort"><img alt="图标 技能 技能分类 物攻.png" /><span>物攻</span></div>
        <div class="rocom_skill_template_skillPower"><div><b>35</b><span>技能威力</span></div></div>
        <div class="rocom_skill_template_skillEffect">✦ 造成物伤，自己回复1能量。</div>
        <div class="rocom_canlearn_box">
          <a href="/rocom/%E9%AD%94%E5%8A%9B%E7%8C%AB" title="魔力猫"><img /></a>
          <a href="/rocom/%E9%AD%94%E5%8A%9B%E7%8C%AB" title="魔力猫"><img /></a>
        </div>
        """

        details = parse_skill_detail(page)

        self.assertEqual(details["attribute"], "普通")
        self.assertEqual(details["energy"], "0")
        self.assertEqual(details["category"], "物攻")
        self.assertEqual(details["power"], "35")
        self.assertEqual(details["effect"], "造成物伤，自己回复1能量。")
        self.assertEqual(
            details["learned_by_pets"],
            [{"name": "魔力猫", "page_url": "https://wiki.biligame.com/rocom/%E9%AD%94%E5%8A%9B%E7%8C%AB"}],
        )

    def test_serialize_entry_strips_links_from_export(self) -> None:
        page = """
        <div class="divsort" data-param1="最终形态" data-param2="光" data-param4="原始形态" data-param5="原始形态" data-param6="否">
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>NO.001</span></a>
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>迪莫</span></a>
          <img src="pet.png" class="rocom_prop_icon" />
          <img src="light.png" class="rocom_pet_icon" />
        </div>
        """
        pet = parse_pets(page)[0]
        pet.characteristics = [{"name": "最好的伙伴", "effect": "回复能量。"}]
        pet.skills = [
            {
                "level": "LV1",
                "name": "抓挠",
                "page_url": "https://wiki.biligame.com/rocom/%E6%8A%93%E6%8C%A0",
                "icon_url": "https://patchwiki.biligame.com/images/skill.png",
                "attribute": "普通",
                "energy": "0",
                "category": "物攻",
                "power": "35",
                "effect": "造成物伤。",
            }
        ]

        exported = serialize_entry(pet)

        self.assertNotIn("page_url", exported)
        self.assertNotIn("image_url", exported)
        self.assertNotIn("attribute_icons", exported)
        self.assertNotIn("source", exported)
        self.assertEqual(exported["characteristics"][0], {"name": "最好的伙伴", "effect": "回复能量。"})
        self.assertEqual(
            exported["skills"][0],
            {
                "level": "LV1",
                "name": "抓挠",
                "attribute": "普通",
                "energy": "0",
                "category": "物攻",
                "power": "35",
                "effect": "造成物伤。",
            },
        )

    def test_write_csv_handles_optional_detail_error_column(self) -> None:
        page = """
        <div class="divsort" data-param1="最终形态" data-param2="光" data-param4="原始形态" data-param5="原始形态" data-param6="否">
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>NO.001</span></a>
          <a href="/rocom/%E8%BF%AA%E8%8E%AB" title="迪莫"><span>迪莫</span></a>
          <img src="pet.png" class="rocom_prop_icon" />
          <img src="light.png" class="rocom_pet_icon" />
        </div>
        """
        pet1 = parse_pets(page)[0]
        pet2 = parse_pets(page)[0]
        pet2.name = "迪莫2"
        pet2.detail_error = "TimeoutError: demo"

        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "pets.csv"
            write_csv(output, [pet1, pet2])
            text = output.read_text(encoding="utf-8-sig")

        self.assertIn("detail_error", text)
        self.assertIn("TimeoutError: demo", text)


if __name__ == "__main__":
    unittest.main()
