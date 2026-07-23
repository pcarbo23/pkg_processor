import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock
from lxml import etree
from pkg_processor.core import PackageProcessor

class TestPackageProcessor(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
    @patch('platform.system', return_value='Linux')
    @patch('subprocess.run')
    def test_processor_with_fallback_decoding(self, mock_run, mock_platform):
        # Create a dummy dtb.zip contents
        dtb_dir = os.path.join(self.test_dir, "dtb_src")
        os.makedirs(dtb_dir)
        
        # 1. Create a dummy OPF file
        opf_content = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://openebook.org/namespaces/oebpackage/1.0/" unique-identifier="uid">
  <metadata>
    <meta name="dtb:audioFormat" content="3gpp"/>
  </metadata>
  <manifest>
    <item id="opf" href="DB12345.opf" media-type="text/xml"/>
    <item id="ncx" href="DB12345.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="smil1" href="DB12345-0001.smil" media-type="application/smil"/>
    <item id="audio1" href="DB12345-0001.3gp" media-type="audio/3gpp"/>
    <item id="hdgs" href="DB12345hdgs.3gp" media-type="audio/3gpp"/>
  </manifest>
  <spine/>
</package>
"""
        with open(os.path.join(dtb_dir, "DB12345.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)
            
        # 2. Create a dummy SMIL file
        smil_content = """<?xml version="1.0" encoding="utf-8"?>
<smil>
  <body>
    <seq id="seq1">
      <par id="h1">
        <text src="DB12345.html#h1"/>
        <audio src="DB12345-0001.3gp" clipBegin="npt=1.500s" clipEnd="npt=13.845s"/>
      </par>
    </seq>
  </body>
</smil>
"""
        with open(os.path.join(dtb_dir, "DB12345-0001.smil"), "w", encoding="utf-8") as f:
            f.write(smil_content)
            
        # 3. Create a dummy NCX file
        ncx_content = """<?xml version="1.0" encoding="utf-8"?>
<ncx version="2005-1">
  <docTitle>
    <text>Title</text>
    <audio src="DB12345hdgs.3gp" clipBegin="0:00:00.000" clipEnd="0:00:03.000"/>
  </docTitle>
  <docAuthor>
    <text>Author</text>
    <audio src="DB12345hdgs.3gp" clipBegin="0:00:03.000" clipEnd="0:00:05.000"/>
  </docAuthor>
  <navMap>
    <navPoint id="np_0001">
      <navLabel>
        <text>Title</text>
        <audio src="DB12345hdgs.3gp" clipBegin="0:00:00.000" clipEnd="0:00:05.000"/>
      </navLabel>
      <content src="DB12345-0001.smil#h1"/>
    </navPoint>
  </navMap>
</ncx>
"""
        with open(os.path.join(dtb_dir, "DB12345.ncx"), "w", encoding="utf-8") as f:
            f.write(ncx_content)
            
        # Create some dummy 3gp file
        with open(os.path.join(dtb_dir, "DB12345-0001.3gp"), "w") as f:
            f.write("dummy 3gp audio content")
            
        # Zip the dtb directory to DB12345.dtb.zip
        dtb_zip_path = os.path.join(self.test_dir, "DB12345.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            for root, _, files in os.walk(dtb_dir):
                for f in files:
                    z.write(os.path.join(root, f), f)
                    
        # Now create the pkg.zip
        pkg_zip_path = os.path.join(self.test_dir, "DB12345.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB12345.dtb.zip")
            
        # Define mock subprocess run behavior for decoder
        def mock_sub_run(cmd, *args, **kwargs):
            # Find the output file parameter
            of_idx = cmd.index("-of")
            out_wav = cmd[of_idx + 1]
            with open(out_wav, "w") as f:
                f.write("mocked wav content decoded")
            return MagicMock(returncode=0)
            
        mock_run.side_effect = mock_sub_run
        
        # Instantiate and run
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        processor.process()
        
        # Verify output master.zip exists
        master_zip_path = os.path.join(self.test_dir, "DB12345.master.zip")
        self.assertTrue(os.path.exists(master_zip_path))
        
        # Verify contents of master.zip
        extracted_master_dir = os.path.join(self.test_dir, "master_extracted")
        os.makedirs(extracted_master_dir)
        with zipfile.ZipFile(master_zip_path, 'r') as z:
            z.extractall(extracted_master_dir)
            
        # Verify files are there
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "DB12345.opf")))
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "DB12345-0001.wav")))
        self.assertFalse(os.path.exists(os.path.join(extracted_master_dir, "DB12345-0001.3gp")))
        self.assertFalse(os.path.exists(os.path.join(extracted_master_dir, "DB12345hdgs.3gp")))
        
        # Verify XML updates
        opf_tree = etree.parse(os.path.join(extracted_master_dir, "DB12345.opf"))
        opf_root = opf_tree.getroot()
        audio_item = opf_root.xpath('//item[@id="audio1"]') or opf_root.xpath('//*[local-name()="item"][@id="audio1"]')
        self.assertEqual(audio_item[0].get('href'), "DB12345-0001.wav")
        self.assertEqual(audio_item[0].get('media-type'), "audio/x-wav")
        
        # Assert headings item is removed from manifest
        hdgs_item = opf_root.xpath('//item[@id="hdgs"]') or opf_root.xpath('//*[local-name()="item"][@id="hdgs"]')
        self.assertEqual(len(hdgs_item), 0)
        
        smil_tree = etree.parse(os.path.join(extracted_master_dir, "DB12345-0001.smil"))
        smil_root = smil_tree.getroot()
        audio_el = smil_root.xpath('//audio') or smil_root.xpath('//*[local-name()="audio"]')
        self.assertEqual(audio_el[0].get('src'), "DB12345-0001.wav")
        
        ncx_tree = etree.parse(os.path.join(extracted_master_dir, "DB12345.ncx"))
        ncx_root = ncx_tree.getroot()
        
        # Assert docTitle and docAuthor elements are updated to first primary audio file and clipTimes
        doc_title_audio = ncx_root.xpath('//docTitle/audio') or ncx_root.xpath('//*[local-name()="docTitle"]//*[local-name()="audio"]')
        self.assertEqual(doc_title_audio[0].get('src'), "DB12345-0001.wav")
        self.assertEqual(doc_title_audio[0].get('clipBegin'), "0:00:01.500")
        self.assertEqual(doc_title_audio[0].get('clipEnd'), "0:00:04.500")
        
        doc_author_audio = ncx_root.xpath('//docAuthor/audio') or ncx_root.xpath('//*[local-name()="docAuthor"]//*[local-name()="audio"]')
        self.assertEqual(doc_author_audio[0].get('src'), "DB12345-0001.wav")
        self.assertEqual(doc_author_audio[0].get('clipBegin'), "0:00:04.500")
        self.assertEqual(doc_author_audio[0].get('clipEnd'), "0:00:06.500")
        
        ncx_audio = ncx_root.xpath('//navMap//audio') or ncx_root.xpath('//*[local-name()="navMap"]//*[local-name()="audio"]')
        self.assertEqual(ncx_audio[0].get('src'), "DB12345-0001.wav")
        self.assertEqual(ncx_audio[0].get('clipBegin'), "npt=1.500s")
        self.assertEqual(ncx_audio[0].get('clipEnd'), "npt=13.845s")

    @patch('subprocess.run')
    def test_processor_with_keep(self, mock_run):
        # Setup similar dummy dtb.zip
        dtb_dir = os.path.join(self.test_dir, "dtb_src_keep")
        os.makedirs(dtb_dir)
        
        opf_content = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://openebook.org/namespaces/oebpackage/1.0/" unique-identifier="uid">
  <metadata><meta name="dtb:audioFormat" content="3gpp"/></metadata>
  <manifest>
    <item id="opf" href="DB99999.opf" media-type="text/xml"/>
    <item id="ncx" href="DB99999.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine/>
</package>
"""
        with open(os.path.join(dtb_dir, "DB99999.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)
        with open(os.path.join(dtb_dir, "DB99999.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB99999.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB99999.opf"), "DB99999.opf")
            z.write(os.path.join(dtb_dir, "DB99999.ncx"), "DB99999.ncx")
            
        # Create a dummy WAV file inside pkg_dir to be zipped
        wav_file_path = os.path.join(self.test_dir, "DB99999-0001.wav")
        with open(wav_file_path, "w") as f:
            f.write("dummy wav content")

        pkg_zip_path = os.path.join(self.test_dir, "DB99999.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB99999.dtb.zip")
            z.write(wav_file_path, "DB99999-0001.wav")
            
        # Run with keep=True
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir, keep=True)
        processor.process()
        
        # Verify the preserved directory exists
        preserved_dir = os.path.join(self.test_dir, "DB99999")
        self.assertTrue(os.path.isdir(preserved_dir))
        self.assertTrue(os.path.exists(os.path.join(preserved_dir, "DB99999.opf")))
        self.assertTrue(os.path.exists(os.path.join(preserved_dir, "DB99999.ncx")))

    @patch('subprocess.run')
    def test_processor_md5_generation(self, mock_run):
        # Setup similar dummy dtb.zip
        dtb_dir = os.path.join(self.test_dir, "dtb_src_md5")
        os.makedirs(dtb_dir)
        
        opf_content = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://openebook.org/namespaces/oeb-package/1.0/" unique-identifier="uid">
  <metadata>
    <dc-metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:Identifier id="uid">DB88888</dc:Identifier>
    </dc-metadata>
    <meta name="dtb:audioFormat" content="3gpp"/>
  </metadata>
  <manifest>
    <item id="opf" href="DB88888.opf" media-type="text/xml"/>
    <item id="ncx" href="DB88888.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine/>
</package>
"""
        with open(os.path.join(dtb_dir, "DB88888.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)
        with open(os.path.join(dtb_dir, "DB88888.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
            
        # Create an old/pre-existing MD5 file in the source to test early delete
        with open(os.path.join(dtb_dir, "DB88888dtb.md5"), "w") as f:
            f.write("old md5 content")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB88888.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB88888.opf"), "DB88888.opf")
            z.write(os.path.join(dtb_dir, "DB88888.ncx"), "DB88888.ncx")
            z.write(os.path.join(dtb_dir, "DB88888dtb.md5"), "DB88888dtb.md5")
            
        # Create a dummy WAV file inside pkg_dir to be zipped
        wav_file_path = os.path.join(self.test_dir, "DB88888-0001.wav")
        with open(wav_file_path, "w") as f:
            f.write("dummy wav content")

        pkg_zip_path = os.path.join(self.test_dir, "DB88888.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB88888.dtb.zip")
            z.write(wav_file_path, "DB88888-0001.wav")
            
        # Run with keep=True
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir, keep=True)
        processor.process()
        
        # Verify the preserved directory exists and contains the correct MD5
        preserved_dir = os.path.join(self.test_dir, "DB88888")
        self.assertTrue(os.path.isdir(preserved_dir))
        
        # Check that the new MD5 is created
        md5_path = os.path.join(preserved_dir, "DB88888dtb.md5")
        self.assertTrue(os.path.exists(md5_path))
        
        # Check that the old MD5 content was overwritten/re-generated
        with open(md5_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("old md5 content", content)
        self.assertIn("<book>DB88888</book>", content)
        
        # Verify output master.zip exists and contains the correct MD5
        master_zip_path = os.path.join(self.test_dir, "DB88888.master.zip")
        self.assertTrue(os.path.exists(master_zip_path))
        with zipfile.ZipFile(master_zip_path, 'r') as z:
            self.assertIn("DB88888dtb.md5", z.namelist())

    def test_processor_with_mp3_fallback_raises_not_implemented(self):
        # Create a dummy dtb.zip with MP3 files
        dtb_dir = os.path.join(self.test_dir, "dtb_src_mp3")
        os.makedirs(dtb_dir)
        
        with open(os.path.join(dtb_dir, "DB11111.opf"), "w", encoding="utf-8") as f:
            f.write('<package><metadata><meta name="dtb:audioFormat" content="MP3"/></metadata><manifest></manifest></package>')
        with open(os.path.join(dtb_dir, "DB11111.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
        with open(os.path.join(dtb_dir, "DB11111-0001.mp3"), "w") as f:
            f.write("dummy mp3 content")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB11111.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB11111.opf"), "DB11111.opf")
            z.write(os.path.join(dtb_dir, "DB11111.ncx"), "DB11111.ncx")
            z.write(os.path.join(dtb_dir, "DB11111-0001.mp3"), "DB11111-0001.mp3")
            
        pkg_zip_path = os.path.join(self.test_dir, "DB11111.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB11111.dtb.zip")
            
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        with self.assertRaises(NotImplementedError) as context:
            processor.process()
        self.assertIn("MP3 fallback decoding is not implemented yet", str(context.exception))

    def test_processor_with_no_audio_raises_file_not_found(self):
        # Create a dummy dtb.zip with no audio files
        dtb_dir = os.path.join(self.test_dir, "dtb_src_no_audio")
        os.makedirs(dtb_dir)
        
        with open(os.path.join(dtb_dir, "DB22222.opf"), "w", encoding="utf-8") as f:
            f.write('<package><metadata></metadata><manifest></manifest></package>')
        with open(os.path.join(dtb_dir, "DB22222.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB22222.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB22222.opf"), "DB22222.opf")
            z.write(os.path.join(dtb_dir, "DB22222.ncx"), "DB22222.ncx")
            
        pkg_zip_path = os.path.join(self.test_dir, "DB22222.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB22222.dtb.zip")
            
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        with self.assertRaises(FileNotFoundError) as context:
            processor.process()
        self.assertIn("No WAV, 3GP, or MP3 audio files found", str(context.exception))

    @patch('platform.system', return_value='Darwin')
    @patch('ctypes.CDLL')
    def test_processor_darwin_ctypes_decoding(self, mock_cdll, mock_platform):
        # Setup mock for ctypes bridge
        mock_bridge = MagicMock()
        mock_bridge.convert_3gp_to_wav.return_value = 0
        mock_cdll.return_value = mock_bridge
        
        # Write dummy wav on bridge call
        def mock_convert(src_bytes, dst_bytes):
            dst = dst_bytes.decode('utf-8')
            with open(dst, "w") as f:
                f.write("mocked wav content decoded via ctypes")
            return 0
        mock_bridge.convert_3gp_to_wav.side_effect = mock_convert
        
        dtb_dir = os.path.join(self.test_dir, "dtb_src_darwin")
        os.makedirs(dtb_dir)
        
        with open(os.path.join(dtb_dir, "DB33333.opf"), "w", encoding="utf-8") as f:
            f.write('<package><metadata><meta name="dtb:audioFormat" content="3gpp"/></metadata><manifest><item id="audio1" href="DB33333-0001.3gp" media-type="audio/3gpp"/><item id="opf" href="DB33333.opf" media-type="text/xml"/><item id="ncx" href="DB33333.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine/></package>')
        with open(os.path.join(dtb_dir, "DB33333.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
        with open(os.path.join(dtb_dir, "DB33333-0001.3gp"), "w") as f:
            f.write("dummy 3gp content")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB33333.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB33333.opf"), "DB33333.opf")
            z.write(os.path.join(dtb_dir, "DB33333.ncx"), "DB33333.ncx")
            z.write(os.path.join(dtb_dir, "DB33333-0001.3gp"), "DB33333-0001.3gp")
            
        pkg_zip_path = os.path.join(self.test_dir, "DB33333.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB33333.dtb.zip")
            
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        
        # We also need to mock Path.exists to say dylib exists
        from pathlib import Path
        orig_exists = Path.exists
        def mock_exists(self_obj):
            if "libamr_bridge.dylib" in str(self_obj):
                return True
            return orig_exists(self_obj)
            
        with patch.object(Path, 'exists', mock_exists):
            processor.process()
            
        # Verify master.zip was created
        master_zip_path = os.path.join(self.test_dir, "DB33333.master.zip")
        self.assertTrue(os.path.exists(master_zip_path))

    @patch('platform.system', return_value='Linux')
    @patch('subprocess.run')
    def test_processor_two_letter_db_prefix_prepending(self, mock_run, mock_platform):
        # Setup legacy dummy layout: prod_id is 'db12345', but files use '12345'
        dtb_dir = os.path.join(self.test_dir, "dtb_src_legacy")
        os.makedirs(dtb_dir)
        
        opf_content = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://openebook.org/namespaces/oebpackage/1.0/" unique-identifier="uid">
  <metadata>
    <meta name="dtb:audioFormat" content="3gpp"/>
  </metadata>
  <manifest>
    <item id="opf" href="12345.opf" media-type="text/xml"/>
    <item id="ncx" href="12345.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="smil1" href="12345-0001.smil" media-type="application/smil"/>
    <item id="audio1" href="12345-0001.3gp" media-type="audio/3gpp"/>
  </manifest>
  <spine/>
</package>
"""
        with open(os.path.join(dtb_dir, "12345.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)
            
        smil_content = """<?xml version="1.0" encoding="utf-8"?>
<smil>
  <body>
    <seq id="seq1">
      <par id="h1">
        <text src="12345.html#h1"/>
        <audio src="12345-0001.3gp" clipBegin="npt=0s" clipEnd="npt=10s"/>
      </par>
    </seq>
  </body>
</smil>
"""
        with open(os.path.join(dtb_dir, "12345-0001.smil"), "w", encoding="utf-8") as f:
            f.write(smil_content)
            
        ncx_content = """<?xml version="1.0" encoding="utf-8"?>
<ncx version="2005-1">
  <navMap>
    <navPoint id="np_0001">
      <navLabel>
        <text>Title</text>
        <audio src="12345hdgs.3gp" clipBegin="npt=0s" clipEnd="npt=5s"/>
      </navLabel>
      <content src="12345-0001.smil#h1"/>
    </navPoint>
  </navMap>
</ncx>
"""
        with open(os.path.join(dtb_dir, "12345.ncx"), "w", encoding="utf-8") as f:
            f.write(ncx_content)
            
        # Create some dummy 3gp file
        with open(os.path.join(dtb_dir, "12345-0001.3gp"), "w") as f:
            f.write("dummy legacy 3gp audio")
            
        # Zip to 12345.dtb.zip (lacking the db prefix)
        dtb_zip_path = os.path.join(self.test_dir, "12345.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "12345.opf"), "12345.opf")
            z.write(os.path.join(dtb_dir, "12345.ncx"), "12345.ncx")
            z.write(os.path.join(dtb_dir, "12345-0001.smil"), "12345-0001.smil")
            z.write(os.path.join(dtb_dir, "12345-0001.3gp"), "12345-0001.3gp")
            
        # Create the main db12345.pkg.zip (with the db prefix in the filename)
        pkg_zip_path = os.path.join(self.test_dir, "db12345.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "12345.dtb.zip")

        # Mock amr-dec decoder
        def mock_sub_run(cmd, *args, **kwargs):
            # Find the output file parameter
            of_idx = cmd.index("-of")
            out_wav = cmd[of_idx + 1]
            with open(out_wav, "w") as f:
                f.write("mocked decoded wav")
            return MagicMock(returncode=0)
        mock_run.side_effect = mock_sub_run
        
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        processor.process()
        
        # Verify output master.zip exists
        master_zip_path = os.path.join(self.test_dir, "db12345.master.zip")
        self.assertTrue(os.path.exists(master_zip_path))
        
        extracted_master_dir = os.path.join(self.test_dir, "master_extracted_legacy")
        os.makedirs(extracted_master_dir)
        with zipfile.ZipFile(master_zip_path, 'r') as z:
            z.extractall(extracted_master_dir)
            
        # Check files inside have had 'db' prepended
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "db12345.opf")))
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "db12345.ncx")))
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "db12345-0001.smil")))
        self.assertTrue(os.path.exists(os.path.join(extracted_master_dir, "db12345-0001.wav")))
        # Check old files without db prefix no longer exist
        self.assertFalse(os.path.exists(os.path.join(extracted_master_dir, "12345.opf")))
        
        # Verify XML contents are correctly reference-updated
        opf_tree = etree.parse(os.path.join(extracted_master_dir, "db12345.opf"))
        opf_root = opf_tree.getroot()
        audio_item = opf_root.xpath('//item[@id="audio1"]') or opf_root.xpath('//*[local-name()="item"][@id="audio1"]')
        self.assertEqual(audio_item[0].get('href'), "db12345-0001.wav")
        
        smil_tree = etree.parse(os.path.join(extracted_master_dir, "db12345-0001.smil"))
        smil_root = smil_tree.getroot()
        audio_el = smil_root.xpath('//audio') or smil_root.xpath('//*[local-name()="audio"]')
        self.assertEqual(audio_el[0].get('src'), "db12345-0001.wav")
        text_el = smil_root.xpath('//text') or smil_root.xpath('//*[local-name()="text"]')
        self.assertEqual(text_el[0].get('src'), "db12345.html#h1")
        
        ncx_tree = etree.parse(os.path.join(extracted_master_dir, "db12345.ncx"))
        ncx_root = ncx_tree.getroot()
        content_el = ncx_root.xpath('//content') or ncx_root.xpath('//*[local-name()="content"]')
        self.assertEqual(content_el[0].get('src'), "db12345-0001.smil#h1")

    @patch('platform.system', return_value='Linux')
    @patch('subprocess.run')
    def test_processor_titauth_ncx_calculation(self, mock_run, mock_platform):
        # Create a dummy dtb.zip contents
        dtb_dir = os.path.join(self.test_dir, "dtb_src_titauth")
        os.makedirs(dtb_dir)
        
        # 1. Create a dummy OPF file
        opf_content = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://openebook.org/namespaces/oebpackage/1.0/" unique-identifier="uid">
  <metadata>
    <meta name="dtb:audioFormat" content="3gpp"/>
  </metadata>
  <manifest>
    <item id="opf" href="DB54321.opf" media-type="text/xml"/>
    <item id="ncx" href="DB54321.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="smil1" href="DB54321-0001.smil" media-type="application/smil"/>
    <item id="audio1" href="DB54321-0001.3gp" media-type="audio/3gpp"/>
    <item id="hdgs" href="DB54321hdgs.3gp" media-type="audio/3gpp"/>
  </manifest>
  <spine/>
</package>
"""
        with open(os.path.join(dtb_dir, "DB54321.opf"), "w", encoding="utf-8") as f:
            f.write(opf_content)
            
        # 2. Create a dummy SMIL file
        smil_content = """<?xml version="1.0" encoding="utf-8"?>
<smil>
  <body>
    <seq id="seq1">
      <par id="h1">
        <text src="DB54321.html#h1"/>
        <audio src="DB54321-0001.3gp" clipBegin="npt=0.072s" clipEnd="npt=13.845s"/>
      </par>
    </seq>
  </body>
</smil>
"""
        with open(os.path.join(dtb_dir, "DB54321-0001.smil"), "w", encoding="utf-8") as f:
            f.write(smil_content)
            
        # 3. Create a dummy NCX file with class="titauth" on a navPoint
        ncx_content = """<?xml version="1.0" encoding="utf-8"?>
<ncx version="2005-1">
  <docTitle>
    <text>Title</text>
    <audio src="DB54321hdgs.3gp" clipBegin="0:00:00.000" clipEnd="0:00:03.100"/>
  </docTitle>
  <docAuthor>
    <text>Author</text>
    <audio src="DB54321hdgs.3gp" clipBegin="0:00:03.100" clipEnd="0:00:05.200"/>
  </docAuthor>
  <navMap>
    <navPoint id="np_0001" class="titauth">
      <navLabel>
        <text>Title/Author Section</text>
        <audio src="DB54321hdgs.3gp" clipBegin="0:00:00.000" clipEnd="0:00:05.200"/>
      </navLabel>
      <content src="DB54321-0001.smil#h1"/>
    </navPoint>
  </navMap>
</ncx>
"""
        with open(os.path.join(dtb_dir, "DB54321.ncx"), "w", encoding="utf-8") as f:
            f.write(ncx_content)
            
        # Create dummy 3gp file
        with open(os.path.join(dtb_dir, "DB54321-0001.3gp"), "w") as f:
            f.write("dummy 3gp audio content")
            
        # Zip to DB54321.dtb.zip
        dtb_zip_path = os.path.join(self.test_dir, "DB54321.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            for root, _, files in os.walk(dtb_dir):
                for f in files:
                    z.write(os.path.join(root, f), f)
                    
        # Now create the pkg.zip
        pkg_zip_path = os.path.join(self.test_dir, "DB54321.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB54321.dtb.zip")
            
        def mock_sub_run(cmd, *args, **kwargs):
            of_idx = cmd.index("-of")
            out_wav = cmd[of_idx + 1]
            with open(out_wav, "w") as f:
                f.write("mocked wav content decoded")
            return MagicMock(returncode=0)
            
        mock_run.side_effect = mock_sub_run
        
        # Instantiate and run
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        processor.process()
        
        # Verify master.zip was created and extracted
        master_zip_path = os.path.join(self.test_dir, "DB54321.master.zip")
        extracted_master_dir = os.path.join(self.test_dir, "master_extracted_titauth")
        os.makedirs(extracted_master_dir)
        with zipfile.ZipFile(master_zip_path, 'r') as z:
            z.extractall(extracted_master_dir)
            
        ncx_tree = etree.parse(os.path.join(extracted_master_dir, "DB54321.ncx"))
        ncx_root = ncx_tree.getroot()
        
        # DocTitle duration: 3.100s, DocAuthor duration: 2.100s
        # BaseTime from smil (0.072)
        # Expected Title Begin: 0.072 -> 0:00:00.072
        # Expected Title End: 0.072 + 3.100 = 3.172 -> 0:00:03.172
        # Expected Author Begin: 3.172 -> 0:00:03.172
        # Expected Author End: 3.172 + 2.100 = 5.272 -> 0:00:05.272
        
        doc_title_audio = ncx_root.xpath('//docTitle/audio') or ncx_root.xpath('//*[local-name()="docTitle"]//*[local-name()="audio"]')
        self.assertEqual(doc_title_audio[0].get('clipBegin'), "0:00:00.072")
        self.assertEqual(doc_title_audio[0].get('clipEnd'), "0:00:03.172")
        
        doc_author_audio = ncx_root.xpath('//docAuthor/audio') or ncx_root.xpath('//*[local-name()="docAuthor"]//*[local-name()="audio"]')
        self.assertEqual(doc_author_audio[0].get('clipBegin'), "0:00:03.172")
        self.assertEqual(doc_author_audio[0].get('clipEnd'), "0:00:05.272")

    @patch('platform.system', return_value='Darwin')
    def test_processor_darwin_missing_library_raises_runtime_error(self, mock_platform):
        dtb_dir = os.path.join(self.test_dir, "dtb_src_darwin_missing")
        os.makedirs(dtb_dir)
        
        with open(os.path.join(dtb_dir, "DB44444.opf"), "w", encoding="utf-8") as f:
            f.write('<package><metadata><meta name="dtb:audioFormat" content="3gpp"/></metadata><manifest><item id="audio1" href="DB44444-0001.3gp" media-type="audio/3gpp"/><item id="opf" href="DB44444.opf" media-type="text/xml"/><item id="ncx" href="DB44444.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine/></package>')
        with open(os.path.join(dtb_dir, "DB44444.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
        with open(os.path.join(dtb_dir, "DB44444-0001.3gp"), "w") as f:
            f.write("dummy 3gp content")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB44444.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB44444.opf"), "DB44444.opf")
            z.write(os.path.join(dtb_dir, "DB44444.ncx"), "DB44444.ncx")
            z.write(os.path.join(dtb_dir, "DB44444-0001.3gp"), "DB44444-0001.3gp")
            
        pkg_zip_path = os.path.join(self.test_dir, "DB44444.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB44444.dtb.zip")
            
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        
        # Explicitly make exists return False
        with patch('pathlib.Path.exists', return_value=False):
            with self.assertRaises(RuntimeError) as context:
                processor.process()
            self.assertIn("Contact NLS/PICS Admin for assistance", str(context.exception))

    @patch('platform.system', return_value='Linux')
    def test_processor_linux_missing_binary_raises_runtime_error(self, mock_platform):
        dtb_dir = os.path.join(self.test_dir, "dtb_src_linux_missing")
        os.makedirs(dtb_dir)
        
        with open(os.path.join(dtb_dir, "DB55555.opf"), "w", encoding="utf-8") as f:
            f.write('<package><metadata><meta name="dtb:audioFormat" content="3gpp"/></metadata><manifest><item id="audio1" href="DB55555-0001.3gp" media-type="audio/3gpp"/><item id="opf" href="DB55555.opf" media-type="text/xml"/><item id="ncx" href="DB55555.ncx" media-type="application/x-dtbncx+xml"/></manifest><spine/></package>')
        with open(os.path.join(dtb_dir, "DB55555.ncx"), "w", encoding="utf-8") as f:
            f.write("<ncx></ncx>")
        with open(os.path.join(dtb_dir, "DB55555-0001.3gp"), "w") as f:
            f.write("dummy 3gp content")
            
        dtb_zip_path = os.path.join(self.test_dir, "DB55555.dtb.zip")
        with zipfile.ZipFile(dtb_zip_path, 'w') as z:
            z.write(os.path.join(dtb_dir, "DB55555.opf"), "DB55555.opf")
            z.write(os.path.join(dtb_dir, "DB55555.ncx"), "DB55555.ncx")
            z.write(os.path.join(dtb_dir, "DB55555-0001.3gp"), "DB55555-0001.3gp")
            
        pkg_zip_path = os.path.join(self.test_dir, "DB55555.pkg.zip")
        with zipfile.ZipFile(pkg_zip_path, 'w') as z:
            z.write(dtb_zip_path, "DB55555.dtb.zip")
            
        processor = PackageProcessor(pkg_zip_path, output_dir=self.test_dir)
        
        # Explicitly make exists return False
        with patch('pathlib.Path.exists', return_value=False):
            with self.assertRaises(RuntimeError) as context:
                processor.process()
            self.assertIn("Contact NLS/PICS Admin for assistance", str(context.exception))

if __name__ == '__main__':
    unittest.main()
