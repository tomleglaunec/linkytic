import pytest

from custom_components.linkytic.parser import (
    HistoricDataset,
    InvalidChecksumError,
    MalformedDatasetError,
    StandardDataset,
    StandardTICParser,
)


def test_parser():
    stream = b'\x02\nADSC\t012345678910\t;\r\nVTIC\t02\tJ\r\nDATE\tH240210121413\t\t6\r\nNGTF\tbase            \t<\r\nLTARF\tBASE            \tF\r\nEAST\t003519703\t+\r\nEASF01\t003519703\t>\r\nEASF02\t000000000\t#\r\nEASF03\t000000000\t$\r\nEASF04\t000000000\t%\r\nEASF05\t000000000\t&\r\nEASF06\t000000000\t\'\r\nEASF07\t000000000\t(\r\nEASF08\t000000000\t)\r\nEASF09\t000000000\t*\r\nEASF10\t000000000\t"\r\nEASD01\t003519703\t<\r\nEASD02\t000000000\t!\r\nEASD03\t000000000\t"\r\nEASD04\t000000000\t#\r\nIRMS1\t001\t/\r\nURMS1\t241\tA\r\nPREF\t06\tE\r\nPCOUP\t06\t_\r\nSINSTS\t00260\tN\r\nSMAXSN\tH240210110331\t00986\t6\r\nSMAXSN-1\tH240209211759\t01422\t^\r\nCCASN\tH240210120000\t00108\t0\r\nCCASN-1\tH240210113000\t00300\tJ\r\nUMOY1\tH240210121000\t241\t"\r\nSTGE\t003A0000\t9\r\nMSG1\tPAS DE          MESSAGE         \t<\r\nPRM\t00000000000000\tA\r\nRELAIS\t001\tC\r\nNTARF\t01\tN\r\nNJOURF\t00\t&\r\nNJOURF+1\t00\tB\r\nPJOURF+1\t0000C001 NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE NONUTILE\tD\r\x03'

    parser = StandardTICParser()
    datasets = parser.parse(stream)
    assert datasets


def test_standard_dataset():
    raw = b"\nADSC\t012345678910\t;\r"
    dataset = StandardDataset(raw)
    assert dataset.tag == "ADSC"
    assert dataset.data == "012345678910"
    assert dataset.timestamp is None


def test_standard_dataset_bad_checksum():
    raw = b"\nADSC\t012345678910\t2\r"
    with pytest.raises(InvalidChecksumError):
        _ = StandardDataset(raw)


def test_standard_dataset_malformed():
    raw = b"\nabcdef\r"
    with pytest.raises(MalformedDatasetError):
        _ = StandardDataset(raw)

def test_historic_dataset():
    raw = b"\nADCO 012345678910 F\r"
    dataset = HistoricDataset(raw)
    assert dataset.tag == "ADCO"
    assert dataset.data == "012345678910"
    assert dataset.timestamp is None


def test_historic_dataset_bad_checksum():
    raw = b"\nADCO 012345678910 2\r"
    with pytest.raises(InvalidChecksumError):
        _ = HistoricDataset(raw)


def test_historic_dataset_malformed():
    raw = b"\nabcdef\r"
    with pytest.raises(MalformedDatasetError):
        _ = HistoricDataset(raw)