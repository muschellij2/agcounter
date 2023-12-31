"""Function for extracting counts."""
from typing import Any

import numpy as np
from numpy import typing as npt
from scipy import signal
import pandas as pd
import gc

# BPF. There are extraneous coefficients as to match constants
# in ActiLife.
# Input data coefficients.
INPUT_COEFFICIENTS: npt.NDArray[np.float_] = np.array(
    [
        [
            -0.009341062898525,
            -0.025470289659360,
            -0.004235264826105,
            0.044152415456420,
            0.036493718347760,
            -0.011893961934740,
            -0.022917390623150,
            -0.006788163862310,
            0.000000000000000,
        ]
    ]
)

# Output data coefficients.
OUTPUT_COEFFICIENTS: npt.NDArray[np.float_] = np.array(
    [
        [
            1.00000000000000000000,
            -3.63367395910957000000,
            5.03689812757486000000,
            -3.09612247819666000000,
            0.50620507633883000000,
            0.32421701566682000000,
            -0.15685485875559000000,
            0.01949130205890000000,
            0.00000000000000000000,
        ]
    ]
)


def _factors(frequency: int):
    if frequency == 30:
        upsample_factor, downsample_factor = 1, 1
    elif frequency == 40:
        upsample_factor, downsample_factor = 3, 4
    elif frequency == 50:
        upsample_factor, downsample_factor = 3, 5
    elif frequency == 60:
        upsample_factor, downsample_factor = 1, 2
    elif frequency == 70:
        upsample_factor, downsample_factor = 3, 7
    elif frequency == 80:
        upsample_factor, downsample_factor = 3, 8
    elif frequency == 90:
        upsample_factor, downsample_factor = 1, 3
    elif frequency == 100:
        upsample_factor, downsample_factor = 3, 10
    else:
        upsample_factor, downsample_factor = 1, 1
    return upsample_factor, downsample_factor


def _extract_slow(
    raw: npt.NDArray[np.float_],
    frequency: int,
    lfe_select: bool,
    epoch: int,
    verbose: bool,
):
    """Extract actigraphy counts from one-dimensional accelerometer data.

    This implementation is purposefully only using basic python function to allow
    easier understanding of the algorithm.

    Parameters
    ----------
    raw
        1D matrix containing raw data
    frequency
        sample frequency of raw data (Hz)
    lfe_select
        False for regular trimming (LFE disabled), True to allow more noise
        (LFE enabled)
    epoch
        Epoch duration in seconds

    Returns
    -------
    ndarray containing epoch counts
    """
    upsample_factor, downsample_factor = _factors(frequency)
    raw = np.transpose(raw)
    # Allocate memory and upsample by factor L.
    upsample_data = np.zeros((1, int(len(raw[0]) * upsample_factor)))

    for i in range(len(raw[0])):
        upsample_data[0, i * upsample_factor] = raw[0, i]

    # Allocate memory and then LPF.  LPF is only done at non integer multiples of 30 Hz.
    # This LPF is garbage and does a poor job of attenuating higher frequencies that
    # need to be rejected.  This is the reason why there is aliasing which causes the
    # "tail" on the epochs.

    # lpf_upsample_data = np.zeros((1, len(upsample_data[0])))
    if frequency not in [30, 60, 90]:
        lpf_upsample_data = np.zeros((1, int(len(raw[0]) * upsample_factor + 1)))

    pi = np.pi  # 3.1415926535897932385
    pi_fp = pi
    a_fp = pi_fp / (pi + 2 * upsample_factor)
    b_fp = (pi - 2 * upsample_factor) / (pi + 2 * upsample_factor)
    l_fp = upsample_factor

    if verbose:
        print("Upsampling data", flush = True)
    if frequency == 30 or frequency == 60 or frequency == 90:
        lpf_upsample_data = upsample_data
    else:
        for i in range(1, len(lpf_upsample_data[0])):
            lpf_upsample_data[0, i] = (
                (a_fp * l_fp) * upsample_data[0, i - 1]
                + (a_fp * l_fp) * upsample_data[0, i - 2]
                - b_fp * lpf_upsample_data[0, i - 1]
            )

    if frequency not in [30, 60, 90]:
        lpf_upsample_data = lpf_upsample_data[:, 1:]

    # Then allocate memory and downsample by factor M.  Downsampled data is rounded to 3
    # decimal places before input into BPF.

    if verbose:
        print("Downsampling data", flush = True)
    if frequency == 30:
        down_sample_data = raw
    else:
        down_sample_data = np.zeros(
            (1, int(np.floor(len(raw[0]) * upsample_factor / downsample_factor)))
        )
        for i in range(len(down_sample_data[0])):
            down_sample_data[0, i] = lpf_upsample_data[0, i * downsample_factor]
    del raw
    gc.collect()
    del lpf_upsample_data
    gc.collect()
    
    down_sample_data = np.round(down_sample_data * 1000) / 1000

    bpf_data = np.zeros((1, len(down_sample_data[0])))

    shift_reg_in = np.zeros((1, 9))
    shift_reg_out = np.zeros((1, 9))

    if verbose:
        print("Filtering data", flush = True)
    for _ in range(180 * 6):  # charge filter up to steady state
        shift_reg_in[[0], 1:9] = shift_reg_in[[0], 0 : (9 - 1)]
        shift_reg_in[0, 0] = down_sample_data[0, 0]
        zeros_comp = np.sum(INPUT_COEFFICIENTS[[0], 0:8] * shift_reg_in[[0], 0:8])
        poles_comp = np.sum(OUTPUT_COEFFICIENTS[[0], 1:8] * shift_reg_out[[0], 0:7])
        bpf_data[0, 0] = zeros_comp - poles_comp
        shift_reg_out[[0], 1:9] = shift_reg_out[[0], 0 : (9 - 1)]
        shift_reg_out[0, 0] = zeros_comp - poles_comp

    for j in range(len(bpf_data[0])):
        shift_reg_in[[0], 1:9] = shift_reg_in[[0], 0:8]
        shift_reg_in[0, 0] = down_sample_data[0, j]
        zeros_comp = np.sum(INPUT_COEFFICIENTS[[0], 0:8] * shift_reg_in[[0], 0:8])
        poles_comp = np.sum(OUTPUT_COEFFICIENTS[[0], 1:8] * shift_reg_out[[0], 0:7])
        bpf_data[0, j] = zeros_comp - poles_comp
        shift_reg_out[[0], 1:9] = shift_reg_out[[0], 0 : (9 - 1)]
        shift_reg_out[0, 0] = zeros_comp - poles_comp
    del down_sample_data
    gc.collect()


    bpf_data = (
        (3.0 / 4096.0) / (2.6 / 256.0) * 237.5
    ) * bpf_data  # 17.127404 is used in ActiLife and 17.128125 is used in firmware.

    if verbose:
        print("Threshold/trimming data", flush = True)
    # then threshold/trim
    trim_data = np.zeros((1, len(bpf_data[0])))

    if lfe_select:
        min_count = 1
        max_count = 128 * 1

        for i in range(len(bpf_data[0])):
            if abs(bpf_data[0, i]) > max_count:
                trim_data[0, i] = max_count
            elif abs(bpf_data[0, i]) < min_count:
                trim_data[0, i] = 0
            elif abs(bpf_data[0, i]) < 4:
                trim_data[0, i] = np.floor(abs(bpf_data[0, i])) - 1
            else:
                trim_data[0, i] = np.floor(abs(bpf_data[0, i]))  # floor
    else:
        min_count = 4
        max_count = 128

        for i in range(len(bpf_data[0])):
            if abs(bpf_data[0, i]) > max_count:
                trim_data[0, i] = max_count
            elif abs(bpf_data[0, i]) < min_count:
                trim_data[0, i] = 0
            else:
                trim_data[0, i] = np.floor(abs(bpf_data[0, i]))  # floor

    if verbose:
        print("Getting data back to 10Hz for accumulation", flush = True)
    del bpf_data
    gc.collect()
    # hackish downsample to 10 Hz
    down_sample10_hz = np.zeros((1, int(len(trim_data[0]) / 3)))

    for y in range(1, len(down_sample10_hz[0]) + 1):
        down_sample10_hz[0, y - 1] = np.floor(
            np.nanmean(trim_data[0, ((y - 1) * 3) : ((y - 1) * 3 + 3)])
        )  # floor
    del trim_data
    gc.collect()

    # Accumulator for epoch
    block_size = epoch * 10
    epoch_counts = np.zeros((1, int((len(down_sample10_hz[0]) / block_size))))

    if verbose:
        print("Summing epochs", flush = True)
    for i in range(len(epoch_counts[0])):
        epoch_counts[0, i] = np.floor(
            sum(down_sample10_hz[0, i * block_size : i * block_size + block_size])
        )
    del down_sample10_hz
    gc.collect()
    return epoch_counts


def _resample(
    raw: npt.NDArray[np.float_], frequency: int, verbose: bool
) -> npt.NDArray[np.float64]:
    """Resample the data.

    Parameters
    ----------
    raw:
        Matrix containing raw data
    frequency:
        sample frequency of raw data (Hz)
    verbose:
        Print diagnostic messages

    Returns
    -------
    resampled_data :
        The resampled_data
    """
    upsample_factor, downsample_factor = _factors(frequency)
    raw = np.transpose(raw)

    # Upsample by factor L.
    m, n = raw.shape
    upsample_data = np.zeros((m, upsample_factor * n), dtype=raw.dtype)
    upsample_data[:, ::upsample_factor] = raw

    if verbose:
        print("_resample: Created upsample data", flush = True)

    pi = np.pi  # 3.1415926535897932385
    a_fp = pi / (pi + 2 * upsample_factor)
    b_fp = (pi - 2 * upsample_factor) / (pi + 2 * upsample_factor)
    up_factor_fp = upsample_factor

    # raw doesn't need to be used after this
    if frequency != 30:
        del raw
    gc.collect()

    # Allocate memory and then LPF.  LPF is only done at non
    # integer multiples of 30 Hz. This LPF is garbage and does a
    # poor job of attenuating higher frequencies that need to be
    # rejected. This is the reason why there is aliasing which
    # causes the "tail" on the epochs.
    if frequency == 30 or frequency == 60 or frequency == 90:
      print("lpf_data not needed", flush = True)
    else:
      if verbose:
          print("_resample: creating lpf data", flush = True)  
      upsample_data = (a_fp * up_factor_fp) * (
        upsample_data + np.roll(upsample_data, 1)
      )
      z = np.zeros(upsample_data.shape[0])
      upsample_data = np.column_stack((z, upsample_data))
      del z

      for i in range(1, len(upsample_data[0])):
         upsample_data[:, i] += -b_fp * upsample_data[:, i - 1]
      # remove the zeros
      upsample_data = upsample_data[:, 1:]
    gc.collect()
    if verbose:
        print("_resample: Created lpf upsample data", flush = True)

    # Then allocate memory and downsample by factor M. Downsampled
    # data is rounded to 3 decimal places before input into BPF.
    if frequency == 30:
        downsample_data = raw
        del raw
    else:
        downsample_data = upsample_data[:, ::downsample_factor]
    gc.collect()

    del upsample_data
    gc.collect()
    
    if verbose:
        print("_resample: Created downsample_data", flush = True)
    downsample_data = np.round(downsample_data * 1000) / 1000
    if verbose:
        print("_resample: returning downsampled data", flush = True)
    return downsample_data


def _bpf_filter(
    downsample_data: npt.NDArray[np.float_], verbose: bool
) -> Any:
    """Run BPF Filter.

    Parameters
    ----------
    downsample_data:
        Matrix containing downsampled data
    verbose:
        Print diagnostic messages

    Returns
    -------
    bpf_data :
        The filtered data
    """
    if verbose:
        print("_bpf_filter: Creating filter", flush = True)    
    a = INPUT_COEFFICIENTS[0, :]
    b = OUTPUT_COEFFICIENTS[0, :]
    zi = signal.lfilter_zi(a, b)
    zi = zi.reshape((1, -1))
    if verbose:
        print("_bpf_filter: Repeating filter", flush = True)    
    zi = zi.repeat(downsample_data.shape[0], axis=0) * downsample_data[:, 0].reshape((-1, 1))
    
    if verbose:
        print("_bpf_filter: Filtering Data", flush = True)
    bpf_data, _ = signal.lfilter(
        a, 
        b,
        downsample_data,
        zi=zi,
    )

    del downsample_data
    gc.collect()

    bpf_data = ((3.0 / 4096.0) / (2.6 / 256.0) * 237.5) * bpf_data
    # 17.127404 is used in ActiLife and 17.128125 is used in
    # firmware.
    return bpf_data


def _trim_data(
    bpf_data: npt.NDArray[np.float_], lfe_select: bool, verbose: bool
) -> Any:
    """Trim/Threshold data.

    Parameters
    ----------
    bpf_data:
        Matrix containing filtered data
    lfe_select:
        False for regular trimming, True for allow more noise
    verbose:
        Print diagnostic messages

    Returns
    -------
    trim_data :
        The trimmed/thresholded data
    """
    # then threshold/trim
    if verbose:
        print("Trimming Data", flush = True)
    if lfe_select:
        min_count = 1
        max_count = 128 * 1

        trim_data = np.abs(bpf_data)
        trim_data[(trim_data < min_count) & (trim_data >= 4)] = 0
        trim_data[trim_data > max_count] = max_count
        mask = (trim_data < 4) & (trim_data >= min_count)
        trim_data[mask] = np.abs(trim_data[mask]) - 1
        trim_data = np.floor(trim_data)
        mask = []

    else:
        min_count = 4
        max_count = 128

        trim_data = np.abs(bpf_data)
        trim_data[trim_data < min_count] = 0
        trim_data[trim_data > max_count] = max_count
        trim_data = np.floor(trim_data)
    return trim_data


def _resample_10hz(
    trim_data: npt.NDArray[np.float_], verbose: bool
) -> npt.NDArray[np.float64]:
    """Resample the data.

    Parameters
    ----------
    trim_data:
        Matrix containing trimmed/thresholded data


    Returns
    -------
    resampled_data :
        The resampled_data
    """
    if verbose:
        print("Getting data back to 10Hz for accumulation", flush = True)
    # hackish downsample to 10 Hz
    downsample_10hz = np.cumsum(trim_data, axis=-1, dtype=float)
    downsample_10hz[:, 3:] = downsample_10hz[:, 3:] - downsample_10hz[:, :-3]
    downsample_10hz = np.floor(downsample_10hz[:, 3 - 1 :: 3] / 3)
    return downsample_10hz


def _sum_counts(
    downsample_10hz: npt.NDArray[np.float_], epoch_seconds: int, verbose: bool
) -> npt.NDArray[np.float64]:
    """Generate counts.

    Parameters
    ----------
    downsample_10hz:
        Matrix containing downsampled to 10hz data
    epoch_seconds:
        Used to compute how many raw samples are used for
        computing an epoch
    verbose:
        Print diagnostic messages

    Returns
    -------
    epochs :
        The epochs
    """
    if verbose:
        print("Summing epochs", flush = True)
    # Accumulator for epoch
    block_size = epoch_seconds * 10
    epoch_counts = np.cumsum(downsample_10hz, axis=-1, dtype=float)

    epoch_counts[:, block_size:] = (
        epoch_counts[:, block_size:] - epoch_counts[:, :-block_size]
    )
    epoch_counts = np.floor(epoch_counts[:, block_size - 1 :: block_size])
    return epoch_counts


def _extract(
    raw: npt.NDArray[np.float_],
    frequency: int,
    lfe_select: bool,
    epoch_seconds: int,
    verbose: bool,
) -> npt.NDArray[np.float64]:
    """Generate counts.

    Parameters
    ----------
    raw:
        Matrix containing raw data
    frequency:
        sample frequency of raw data (Hz)
    lfe_select:
        False for regular trimming, True for allow more noise
    epoch_seconds:
        Used to compute how many raw samples are used for
        computing an epoch
    verbose:
        Print diagnostic messages

    Returns
    -------
    epochs :
        The epochs
    """
    if verbose:
      print("_resampling data", flush=True)  
    downsample_data = _resample(raw=raw, frequency=frequency, verbose=verbose)
    del raw
    gc.collect()
    if verbose:
      print("_bpf_filtering data", flush=True)  
    bpf_data = _bpf_filter(downsample_data=downsample_data, verbose=verbose)
    del downsample_data
    gc.collect()
    if verbose:
      print("_trim_data-ing data", flush=True)     
    trim_data = _trim_data(bpf_data=bpf_data, lfe_select=lfe_select, verbose=verbose)
    del bpf_data
    gc.collect()
    if verbose:
      print("_resample_10hz-ing data", flush=True)      
    downsample_10hz = _resample_10hz(trim_data=trim_data, verbose=verbose)
    del trim_data
    gc.collect()

    epoch_counts = _sum_counts(
        downsample_10hz=downsample_10hz, epoch_seconds=epoch_seconds, verbose=verbose
    )
    return epoch_counts


def get_counts(raw, freq: int, epoch: int, fast: bool = True, verbose: bool = False):
    """
    Generate counts from raw data.

    Parameters
    ----------
    raw : ndarray, shape (n_samples, 3)
        Raw data matrix, in x, y, z directions for 1st, 2nd, 3rd columns.
    freq : int
        Sampling frequency, has to be 30, 40, 50, 60, 70, 80, 90 or 100 Hz.
    epoch : int
        Epoch length (seconds).
    fast:
        Use fast implementation

    Returns
    -------
    counts : ndarray, shape (n_epochs, 3)
        The counts, n_epochs = ceil(n_samples/freq).
    """
    assert freq in range(30, 101, 10), "freq must be in [30 : 10 : 100]"

    if fast:
        counts = _extract(raw, freq, False, epoch, verbose).transpose()
    else:
        x_raw = raw[0 : len(raw), [0]]
        y_raw = raw[0 : len(raw), [1]]
        z_raw = raw[0 : len(raw), [2]]

        if verbose:
            print("Running extract for x", flush = True)
        epoch_counts_x = _extract_slow(x_raw, freq, False, epoch, verbose)
        if verbose:
            print("Running extract for y", flush = True)
        epoch_counts_y = _extract_slow(y_raw, freq, False, epoch, verbose)
        if verbose:
            print("Running extract for z", flush = True)
        epoch_counts_z = _extract_slow(z_raw, freq, False, epoch, verbose)

        if verbose:
            print("Transposing and concatenating", flush = True)
        # formatting matrix for output
        x_counts_transposed = np.transpose(epoch_counts_x)
        del epoch_counts_x
        y_counts_transposed = np.transpose(epoch_counts_y)
        del epoch_counts_y
        z_counts_transposed = np.transpose(epoch_counts_z)
        del epoch_counts_z
        gc.collect()
        
        counts = np.concatenate(
            (x_counts_transposed, y_counts_transposed, z_counts_transposed), 1
        )
        del x_counts_transposed
        del y_counts_transposed
        del z_counts_transposed
        gc.collect()

    return counts.astype(int)


def get_counts_csv(file, freq: int, epoch: int, fast: bool = True, verbose: bool = False, time_column: str = None):
  if verbose:
    print("Reading in CSV", flush = True)
  raw = pd.read_csv(file, skiprows=0)
  if time_column is not None:
    ts = raw[time_column]
    ts = pd.to_datetime(ts)
    time_freq = str(epoch) + 'S'
    ts = ts.dt.round(time_freq)
    ts = ts.unique()
    ts = pd.DataFrame(ts, columns=[time_column])
  raw = raw[["X", "Y", "Z"]]
  if verbose:
    print("Converting to array", flush = True)  
  raw = np.array(raw)
  gc.collect()
  if verbose:
    print("Getting Counts", flush = True)    
  counts = get_counts(raw, freq = freq, epoch = epoch, fast = fast, verbose = verbose)
  del raw
  gc.collect()
  counts = pd.DataFrame(counts, columns = ['X','Y','Z'])
  counts["AC"] = ((counts["X"]* 1.0) ** 2.0 + (counts["Y"]*1.0)  ** 2.0 + (counts["Z"] * 1.0) **2.0) ** 0.5
  if time_column is not None:
    ts = ts[0:counts.shape[0]]
    counts = pd.concat([ts, counts], axis=1)
  return counts

def convert_counts_csv(file, outfile, freq: int, epoch: int, fast: bool = True, verbose: bool = False, time_column: str = None):
  counts = get_counts_csv(file, freq = freq, epoch = epoch, verbose = True, time_column = time_column)
  counts.to_csv(outfile,index=False)
  return counts
