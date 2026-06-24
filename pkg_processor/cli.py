import argparse
import sys
from pkg_processor.core import PackageProcessor

def main():
    parser = argparse.ArgumentParser(
        description="PICS Package Process - Converts 1206:2025 compliant talking book packages to Z39.86-2002 compliant WAV DTBs."
    )
    parser.add_argument("pkg_zip", help="Path to the input pkg.zip file")
    parser.add_argument("-o", "--output-dir", help="Directory where the output master.zip will be saved")
    parser.add_argument("-d", "--decoder", default="decAmrWbp", help="Path to the AMR-WB+ decoder binary (default: decAmrWbp)")
    parser.add_argument("-k", "--keep", action="store_true", help="Preserve the converted files in a directory named after the prodID")
    
    args = parser.parse_args()
    
    try:
        processor = PackageProcessor(
            pkg_zip_path=args.pkg_zip,
            output_dir=args.output_dir,
            decoder_path=args.decoder,
            keep=args.keep
        )
        processor.process()
        print(f"Successfully processed package. Output master zip created in {processor.output_dir}")
    except Exception as e:
        print(f"Error processing package: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
