###
# This tool is for PICS2. Convert a 1206:2025 pkg to a Master Wav DTB packaged in a master.zip
###

import os
import re
import shutil
import zipfile
import subprocess
import platform
import ctypes
import tempfile
from pathlib import Path
from lxml import etree

class PackageProcessor:
    def __init__(self, pkg_zip_path, output_dir=None, keep=False):
        self.pkg_zip_path = os.path.abspath(pkg_zip_path)
        self.keep = keep
        
        # Get prodID from the zip filename (e.g., DB12345.pkg.zip -> DB12345)
        base_name = os.path.basename(self.pkg_zip_path)
        self.prod_id = re.sub(r'\.pkg\.zip$', '', base_name, flags=re.IGNORECASE)
        
        # Legacy two-letter prefix detection
        if self.prod_id.lower().startswith('db'):
            self.prefix_to_prepend = self.prod_id[:2]
            self.legacy_pattern = self.prod_id[2:]
        else:
            self.prefix_to_prepend = None
            self.legacy_pattern = None

        if output_dir is None:
            self.output_dir = os.path.dirname(self.pkg_zip_path)
        else:
            self.output_dir = os.path.abspath(output_dir)

    def rename_legacy_files(self, directory):
        if not self.prefix_to_prepend or not self.legacy_pattern:
            return
        for root, _, files in os.walk(directory):
            for f in files:
                if f.lower().startswith(self.legacy_pattern.lower()) and not f.lower().startswith(self.prod_id.lower()):
                    old_path = os.path.join(root, f)
                    new_name = self.prefix_to_prepend + f
                    new_path = os.path.join(root, new_name)
                    os.rename(old_path, new_path)

    def normalize_href(self, href):
        if not href:
            return href
        if href.startswith(('http://', 'https://', '#')):
            return href
        
        parts = href.split('#')
        file_part = parts[0]
        fragment = f"#{parts[1]}" if len(parts) > 1 else ""
        
        if self.prefix_to_prepend and self.legacy_pattern:
            path_prefix = ""
            if file_part.startswith("./"):
                path_prefix = "./"
                file_part = file_part[2:]
            if file_part.lower().startswith(self.legacy_pattern.lower()) and not file_part.lower().startswith(self.prod_id.lower()):
                file_part = self.prefix_to_prepend + file_part
            return path_prefix + file_part + fragment
        return href

    def process(self):
        # Create a temp directory for extraction
        temp_dir = os.path.join(self.output_dir, f"temp_{self.prod_id}")
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            # 1. Extract pkg.zip
            with zipfile.ZipFile(self.pkg_zip_path, 'r') as pkg_zip:
                pkg_zip.extractall(temp_dir)
            
            # Rename legacy files inside temp_dir
            self.rename_legacy_files(temp_dir)

            # Find dtb.zip
            dtb_zip_name = f"{self.prod_id}.dtb.zip"
            possible_names = [dtb_zip_name]
            if self.legacy_pattern:
                possible_names.append(f"{self.legacy_pattern}.dtb.zip")
                
            dtb_zip_path = None
            for f in os.listdir(temp_dir):
                if f.lower() in [n.lower() for n in possible_names]:
                    dtb_zip_path = os.path.join(temp_dir, f)
                    break
            
            if not dtb_zip_path or not os.path.exists(dtb_zip_path):
                raise FileNotFoundError(f"Could not find dtb.zip in package for {self.prod_id}")
            
            # Extract dtb.zip
            dtb_extract_dir = os.path.join(temp_dir, "dtb_extracted")
            os.makedirs(dtb_extract_dir, exist_ok=True)
            with zipfile.ZipFile(dtb_zip_path, 'r') as dtb_zip:
                dtb_zip.extractall(dtb_extract_dir)
            
            # Rename legacy files inside dtb_extracted directory
            self.rename_legacy_files(dtb_extract_dir)
            
            # Early delete of any existing MD5 digest files in the source dtb.zip
            for f in os.listdir(dtb_extract_dir):
                if f.lower().endswith('.md5'):
                    os.remove(os.path.join(dtb_extract_dir, f))
            
            # 2. Discover WAV files
            wav_files = [f for f in os.listdir(temp_dir) if f.lower().endswith('.wav')]
            
            # If no WAV files, use fallback AMR-WB+ decoder
            if not wav_files:
                # Check for MP3 files first in the extracted directories
                mp3_files = []
                for root, _, files in os.walk(temp_dir):
                    for f in files:
                        if f.lower().endswith('.mp3'):
                            mp3_files.append(os.path.join(root, f))
                if mp3_files:
                    raise NotImplementedError("MP3 fallback decoding is not implemented yet.")
                
                # Check if there are any 3GP files
                three_gp_files = []
                for root, _, files in os.walk(temp_dir):
                    for f in files:
                        if f.lower().endswith('.3gp'):
                            three_gp_files.append(os.path.join(root, f))
                
                if not three_gp_files:
                    raise FileNotFoundError("No WAV, 3GP, or MP3 audio files found in package.")
                
                self.decode_amr_wb_plus(temp_dir, dtb_extract_dir)
                # Re-check WAV files
                wav_files = [f for f in os.listdir(temp_dir) if f.lower().endswith('.wav')]
                if not wav_files:
                    # Maybe they were inside the dtb_extracted directory or need to be decoded from there?
                    self.decode_amr_wb_plus(temp_dir, dtb_extract_dir)
                    wav_files = [f for f in os.listdir(temp_dir) if f.lower().endswith('.wav')]
                    if not wav_files:
                        raise FileNotFoundError("AMR-WB+ decoding did not produce any WAV files.")
            
            # 3. Edit XML Files (OPF, SMIL, NCX)
            self.update_dtb_files(dtb_extract_dir, temp_dir)
            
            # Move all WAV files to the dtb directory so they are packaged together
            for f in os.listdir(temp_dir):
                if f.lower().endswith('.wav'):
                    shutil.move(os.path.join(temp_dir, f), os.path.join(dtb_extract_dir, f))
            
            # Remove any .3gp or hdgs files from the dtb directory so they are not packaged
            for root, _, files in os.walk(dtb_extract_dir):
                for f in files:
                    if f.lower().endswith('.3gp') or 'hdgs' in f.lower():
                        try:
                            os.remove(os.path.join(root, f))
                        except FileNotFoundError:
                            pass
 
            # Generate the new NLS-compliant MD5 digest
            from nls_md5sum import process_directory
            process_directory(dtb_extract_dir)
 
            # 4. Package as uncompressed storage zip
            output_zip_path = os.path.join(self.output_dir, f"{self.prod_id}.master.zip")
            self.create_uncompressed_zip(dtb_extract_dir, output_zip_path)
 
            # Preserve material if keep flag is true
            if self.keep:
                dest_keep_dir = os.path.join(self.output_dir, self.prod_id)
                if os.path.exists(dest_keep_dir):
                    shutil.rmtree(dest_keep_dir)
                shutil.copytree(dtb_extract_dir, dest_keep_dir)
            
        finally:
            # Clean up temp files
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
    def decode_amr_wb_plus(self, target_wav_dir, source_dir):
        # Look for any .3gp files in source_dir or target_wav_dir
        three_gp_files = []
        for root, _, files in os.walk(source_dir):
            for f in files:
                if f.lower().endswith('.3gp'):
                    three_gp_files.append(os.path.join(root, f))
                    
        for root, _, files in os.walk(target_wav_dir):
            for f in files:
                if f.lower().endswith('.3gp') and os.path.join(root, f) not in three_gp_files:
                    three_gp_files.append(os.path.join(root, f))
                    
        if not three_gp_files:
            raise FileNotFoundError("No WAV files found and no AMR-WB+ (.3gp) files available for fallback decoding.")
            
        os_type = platform.system()
        lib_dir = Path(__file__).parent.absolute()

        for gp_file in three_gp_files:
            wav_name = os.path.splitext(os.path.basename(gp_file))[0] + ".wav"
            wav_path = os.path.join(target_wav_dir, wav_name)
            
            if os_type == 'Darwin':
                lib_path = lib_dir / "libamr_bridge.dylib"
                if not lib_path.exists():
                    raise RuntimeError(f"AMR-WB+ decoder library not found at {lib_path}")
                try:
                    bridge = ctypes.CDLL(str(lib_path))
                    bridge.convert_3gp_to_wav.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
                    bridge.convert_3gp_to_wav.restype = ctypes.c_int
                    
                    result = bridge.convert_3gp_to_wav(
                        str(gp_file).encode('utf-8'),
                        str(wav_path).encode('utf-8')
                    )
                    if result != 0:
                        raise RuntimeError(f"AMR decoding failed with code {result}")
                except Exception as e:
                    raise RuntimeError(f"Failed to load or execute AMR-WB+ decoder library: {e}")
            elif os_type == 'Linux':
                binary_path = lib_dir / "amr-dec"
                if not binary_path.exists():
                    raise RuntimeError(f"AMR-WB+ decoder binary not found at {binary_path}")
                try:
                    subprocess.run(
                        [str(binary_path), '-fs', '41000', '-if', str(gp_file), '-of', str(wav_path)],
                        check=True,
                        capture_output=True
                    )
                except Exception as e:
                    raise RuntimeError(f"AMR decoding failed using binary: {e}")
            elif os_type == 'Windows':
                raise NotImplementedError("AMR-WB+ decoding is not currently supported on Windows.")
            else:
                raise NotImplementedError(f"AMR-WB+ decoding is not supported on platform: {os_type}")

    def update_dtb_files(self, dtb_dir, wav_dir):
        # Find OPF, NCX, SMIL files
        opf_file = None
        ncx_file = None
        smil_files = []
        
        for f in os.listdir(dtb_dir):
            if f.lower().endswith('.opf'):
                opf_file = os.path.join(dtb_dir, f)
            elif f.lower().endswith('.ncx'):
                ncx_file = os.path.join(dtb_dir, f)
            elif f.lower().endswith('.smil'):
                smil_files.append(os.path.join(dtb_dir, f))
                
        if not opf_file or not ncx_file:
            raise FileNotFoundError("Could not find OPF or NCX files in the extracted DTB.")
            
        # Parse all SMIL files first to build a mapping from SMIL element ID to audio source/times
        smil_elements = {}
        for smil_path in smil_files:
            smil_name = os.path.basename(smil_path)
            parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
            tree = etree.parse(smil_path, parser)
            root = tree.getroot()
            
            # Normalize and update all src / href attributes in SMIL
            for el in root.iter():
                for attr in ['src', 'href']:
                    val = el.get(attr)
                    if val:
                        normalized = self.normalize_href(val)
                        if attr == 'src' and el.tag.endswith('audio') and normalized.lower().endswith('.3gp'):
                            normalized = re.sub(r'\.3gp$', '.wav', normalized, flags=re.IGNORECASE)
                        elif attr == 'src' and el.tag.endswith('audio') and normalized.lower().endswith('.wav'):
                            # just to be safe
                            pass
                        el.set(attr, normalized)
            
            # Collect elements (like par, seq) that have audio elements inside them
            for parent in root.xpath('//par') + root.xpath('//*[local-name()="par"]') + root.xpath('//seq') + root.xpath('//*[local-name()="seq"]'):
                pid = parent.get('id')
                if pid:
                    audio_el = parent.find('.//audio')
                    if audio_el is None:
                        audio_el = parent.find('.//*[local-name()="audio"]')
                    if audio_el is not None:
                        smil_elements[f"{smil_name}#{pid}"] = {
                            'src': audio_el.get('src'),
                            'clipBegin': audio_el.get('clipBegin'),
                            'clipEnd': audio_el.get('clipEnd')
                        }
            
            # Save modified SMIL file
            tree.write(smil_path, encoding='utf-8', xml_declaration=True, pretty_print=False)

        # Update OPF
        opf_parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
        opf_tree = etree.parse(opf_file, opf_parser)
        opf_root = opf_tree.getroot()
        
        # Change manifest item media-types and hrefs, and remove hdgs manifest items
        for item in opf_root.xpath('//item') + opf_root.xpath('//*[local-name()="item"]'):
            href = item.get('href')
            media_type = item.get('media-type')
            if href:
                if 'hdgs' in href.lower():
                    item.getparent().remove(item)
                    continue
                normalized_href = self.normalize_href(href)
                if normalized_href.lower().endswith('.3gp'):
                    normalized_href = re.sub(r'\.3gp$', '.wav', normalized_href, flags=re.IGNORECASE)
                item.set('href', normalized_href)
            if media_type == 'audio/3gpp':
                item.set('media-type', 'audio/x-wav')
                
        # Change audioFormat metadata to WAV
        for meta in opf_root.xpath('//meta') + opf_root.xpath('//*[local-name()="meta"]'):
            name = meta.get('name')
            if name == 'dtb:audioFormat':
                meta.set('content', 'WAV')
                
        opf_tree.write(opf_file, encoding='utf-8', xml_declaration=True, pretty_print=False)

        # Update NCX
        ncx_parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
        ncx_tree = etree.parse(ncx_file, ncx_parser)
        ncx_root = ncx_tree.getroot()
        
        # Normalize and update all src / href attributes in NCX first
        for el in ncx_root.iter():
            for attr in ['src', 'href']:
                val = el.get(attr)
                if val:
                    normalized = self.normalize_href(val)
                    el.set(attr, normalized)

        # Locate the first navPoint to calculate translation offset for docTitle and docAuthor
        first_navpoint_primary_audio = None
        translation_offset = 0.0
        
        def parse_seconds(time_str):
            if not time_str:
                return 0.0
            time_str = time_str.strip().lower()
            if time_str.startswith('npt='):
                time_str = time_str[4:]
            if time_str.endswith('s'):
                time_str = time_str[:-1]
                
            if ':' in time_str:
                parts = time_str.split(':')
                try:
                    if len(parts) == 3:
                        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:
                        return float(parts[0]) * 60 + float(parts[1])
                except ValueError:
                    return 0.0
            else:
                try:
                    return float(time_str)
                except ValueError:
                    return 0.0
                
        def format_npt(seconds):
            return f"npt={seconds:.3f}s"

        for nav_point in ncx_root.xpath('//navPoint') + ncx_root.xpath('//*[local-name()="navPoint"]'):
            content = nav_point.find('content')
            if content is None:
                content = nav_point.find('.//*[local-name()="content"]')
            if content is not None:
                c_src = content.get('src')
                if c_src:
                    parts = c_src.split('#')
                    if len(parts) == 2:
                        smil_file_ref = os.path.basename(parts[0])
                        smil_id_ref = parts[1]
                        key = f"{smil_file_ref}#{smil_id_ref}"
                        if key in smil_elements:
                            smil_audio = smil_elements[key]
                            nav_label = nav_point.find('navLabel')
                            if nav_label is None:
                                nav_label = nav_point.find('.//*[local-name()="navLabel"]')
                            if nav_label is not None:
                                audio_el = nav_label.find('audio')
                                if audio_el is None:
                                    audio_el = nav_label.find('.//*[local-name()="audio"]')
                                if audio_el is not None:
                                    h_start = parse_seconds(audio_el.get('clipBegin'))
                                    p_start = parse_seconds(smil_audio['clipBegin'])
                                    translation_offset = p_start - h_start
                                    first_navpoint_primary_audio = smil_audio['src']
                                    break

        if not first_navpoint_primary_audio:
            first_navpoint_primary_audio = f"{self.prod_id}-0001.wav"
            translation_offset = 0.0

        # Locate the titauth (Title/Author) navPoint or first navPoint
        titauth_navpoint = None
        for nav_point in ncx_root.xpath('//navPoint') + ncx_root.xpath('//*[local-name()="navPoint"]'):
            np_id = nav_point.get('id') or ''
            np_class = nav_point.get('class') or ''
            if 'titauth' in np_id.lower() or 'titauth' in np_class.lower():
                titauth_navpoint = nav_point
                break
        
        if titauth_navpoint is None:
            navpoints = ncx_root.xpath('//navPoint') + ncx_root.xpath('//*[local-name()="navPoint"]')
            if navpoints:
                titauth_navpoint = navpoints[0]

        # Extract the clipBegin time of the titauth navPoint from the new/output .wav file mapping (e.g., 0:00:00.072). This is our BaseTime.
        base_time = 0.0
        primary_audio_file = None
        
        if titauth_navpoint is not None:
            content = titauth_navpoint.find('content')
            if content is None:
                content = titauth_navpoint.find('.//*[local-name()="content"]')
            if content is not None:
                c_src = content.get('src')
                if c_src:
                    parts = c_src.split('#')
                    if len(parts) == 2:
                        smil_file_ref = os.path.basename(parts[0])
                        smil_id_ref = parts[1]
                        key = f"{smil_file_ref}#{smil_id_ref}"
                        if key in smil_elements:
                            base_time = parse_seconds(smil_elements[key]['clipBegin'])
                            primary_audio_file = smil_elements[key]['src']

        if not primary_audio_file:
            primary_audio_file = first_navpoint_primary_audio

        def format_hms(seconds):
            total_ms = int(round(seconds * 1000))
            ms = total_ms % 1000
            total_s = total_ms // 1000
            s = total_s % 60
            total_m = total_s // 60
            m = total_m % 60
            h = total_m // 60
            return f"{h}:{m:02d}:{s:02d}.{ms:03d}"

        # Calculate duration of docTitle and docAuthor using legacy NCX file
        doc_title_duration = 0.0
        doc_author_duration = 0.0

        doc_title_elements = ncx_root.xpath('//docTitle') + ncx_root.xpath('//*[local-name()="docTitle"]')
        if doc_title_elements:
            dt_audio_els = doc_title_elements[0].xpath('.//audio') + doc_title_elements[0].xpath('.//*[local-name()="audio"]')
            if dt_audio_els:
                dt_audio = dt_audio_els[0]
                dt_begin = parse_seconds(dt_audio.get('clipBegin'))
                dt_end = parse_seconds(dt_audio.get('clipEnd'))
                doc_title_duration = max(0.0, dt_end - dt_begin)

        doc_author_elements = ncx_root.xpath('//docAuthor') + ncx_root.xpath('//*[local-name()="docAuthor"]')
        if doc_author_elements:
            da_audio_els = doc_author_elements[0].xpath('.//audio') + doc_author_elements[0].xpath('.//*[local-name()="audio"]')
            if da_audio_els:
                da_audio = da_audio_els[0]
                da_begin = parse_seconds(da_audio.get('clipBegin'))
                da_end = parse_seconds(da_audio.get('clipEnd'))
                doc_author_duration = max(0.0, da_end - da_begin)

        # Step D: Set the new <docTitle> clipBegin equal to the BaseTime.
        doc_title_begin = base_time
        # Step E: Set the new <docTitle> clipEnd equal to (BaseTime + <docTitle> duration).
        doc_title_end = base_time + doc_title_duration
        # Step F: Set the new <docAuthor> clipBegin equal to the new <docTitle> clipEnd.
        doc_author_begin = doc_title_end
        # Step G: Set the new <docAuthor> clipEnd equal to (new <docAuthor> clipBegin + <docAuthor> duration).
        doc_author_end = doc_author_begin + doc_author_duration

        if doc_title_elements and doc_title_elements[0].xpath('.//audio') + doc_title_elements[0].xpath('.//*[local-name()="audio"]'):
            dt_audio = (doc_title_elements[0].xpath('.//audio') + doc_title_elements[0].xpath('.//*[local-name()="audio"]'))[0]
            dt_audio.set('src', primary_audio_file)
            dt_audio.set('clipBegin', format_hms(doc_title_begin))
            dt_audio.set('clipEnd', format_hms(doc_title_end))

        if doc_author_elements and doc_author_elements[0].xpath('.//audio') + doc_author_elements[0].xpath('.//*[local-name()="audio"]'):
            da_audio = (doc_author_elements[0].xpath('.//audio') + doc_author_elements[0].xpath('.//*[local-name()="audio"]'))[0]
            da_audio.set('src', primary_audio_file)
            da_audio.set('clipBegin', format_hms(doc_author_begin))
            da_audio.set('clipEnd', format_hms(doc_author_end))

        # Map NCX clipTimes from SMIL
        for nav_point in ncx_root.xpath('//navPoint') + ncx_root.xpath('//*[local-name()="navPoint"]'):
            content = nav_point.find('content')
            if content is None:
                content = nav_point.find('.//*[local-name()="content"]')
            if content is None:
                continue
                
            c_src = content.get('src')
            if not c_src:
                continue
                
            parts = c_src.split('#')
            if len(parts) != 2:
                continue
            smil_file_ref = os.path.basename(parts[0])
            smil_id_ref = parts[1]
            key = f"{smil_file_ref}#{smil_id_ref}"
            
            if key in smil_elements:
                smil_audio = smil_elements[key]
                # Find audio element in navLabel
                nav_label = nav_point.find('navLabel')
                if nav_label is None:
                    nav_label = nav_point.find('.//*[local-name()="navLabel"]')
                if nav_label is not None:
                    audio_el = nav_label.find('audio')
                    if audio_el is None:
                        audio_el = nav_label.find('.//*[local-name()="audio"]')
                    if audio_el is not None:
                        audio_el.set('src', smil_audio['src'])
                        if smil_audio['clipBegin']:
                            audio_el.set('clipBegin', smil_audio['clipBegin'])
                        if smil_audio['clipEnd']:
                            audio_el.set('clipEnd', smil_audio['clipEnd'])
                            
        ncx_tree.write(ncx_file, encoding='utf-8', xml_declaration=True, pretty_print=False)

    def create_uncompressed_zip(self, source_dir, output_zip_path):
        # Create uncompressed zip (compression level 0 / ZIP_STORED)
        # All files must be added with ZIP_STORED
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for root, _, files in os.walk(source_dir):
                for f in files:
                    full_path = os.path.join(root, f)
                    rel_path = os.path.relpath(full_path, source_dir)
                    zf.write(full_path, rel_path)
