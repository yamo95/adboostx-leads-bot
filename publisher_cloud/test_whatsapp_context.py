import unittest
import contact_context as c

class WhatsappContextTests(unittest.TestCase):
    def rows(self, html, path='/contact-us/'):
        return c.parse(html,'https://publisher.example'+path)[0]
    def test_label_split_from_international_number(self):
        rows=self.rows('<p><strong>WhatsApp Number:</strong> +92 329 3906927</p>')
        self.assertEqual(rows[0]['contact'],'+923293906927')
        self.assertEqual(rows[0]['role'],'contact')
    def test_heading_itself_is_contact_block(self):
        self.assertEqual(self.rows('<h5>WhatsApp: <span>+92 329 3906927</span></h5>')[0]['contact'],'+923293906927')
    def test_separate_heading_and_number_with_hours(self):
        rows=self.rows('<h3>Call / WhatsApp</h3><p>10 AM - 7 PM, Mon-Sat</p><p>+91 73690 54761</p>')
        self.assertEqual(rows[0]['contact'],'+917369054761')
    def test_unlabelled_phone_never_inferred(self):
        self.assertEqual(self.rows('<p>Phone: <strong>+92 329 3906927</strong></p>'),[])
    def test_label_does_not_leak_across_heading(self):
        self.assertEqual(self.rows('<h3>WhatsApp</h3><h3>Other supplier</h3><p>+91 73690 54761</p>'),[])
    def test_recovery_does_not_promote_seo_section(self):
        rows=self.rows('<p>Guest post and backlink services</p><p><strong>WhatsApp:</strong><span>+923293906927</span></p>')
        self.assertEqual(rows,[])
    def test_recovery_does_not_read_hidden_or_forms(self):
        self.assertEqual(self.rows('<form><p>WhatsApp: <b>+923293906927</b></p></form><p hidden>WhatsApp: <b>+923293906927</b></p>'),[])
    def test_recovery_restricted_to_contact_pages(self):
        self.assertEqual(self.rows('<p>WhatsApp: <strong>+923293906927</strong></p>','/apps/whatsapp-guide'),[])
    def test_no_guess_for_missing_country_code(self):
        self.assertEqual(self.rows('<p>WhatsApp Number: <b>03293906927</b></p>'),[])
    def test_legal_page_not_promoted_by_label_recovery(self):
        self.assertEqual(self.rows('<p>WhatsApp Number: <b>+923293906927</b></p>','/privacy-policy'),[])

if __name__=='__main__':unittest.main()
