#!/usr/bin/python3

import os, sys
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib import collections
from matplotlib.patches import Rectangle
from matplotlib import cm
from collections import Counter
import pandas as pd
import subprocess as sp
plt.rcParams['savefig.dpi'] = 300
import matplotlib.colors as mcolors

from hatchet.utils.ArgParsing import parse_plot_cn_1d2d_args
from hatchet.utils import Supporting as sp
from importlib.resources import path
import hatchet.resources
from hatchet import config, __version__

plt.style.use('ggplot')
sns.set_style("whitegrid")

def main(args=None):
    sp.log("# Checking and parsing input arguments\n")
    args = parse_plot_cn_1d2d_args(args)
    sp.logArgs(args, 80)

    ### THESE VARIABLES ARE CURRENTLY DUMMIES ###
    # Consider exposing these as command-line arguments in the future
    title = None
    reflect_baf = False
    show_centromeres = False
    genome_version = None
    resample_balanced = False

    if show_centromeres: 
        # Reference genome version is only used to locate centromeres
        if args.genome_version not in ['hg19', 'hg38']:
            # throw HATCHet error
            raise ValueError(f"GENOME VERSION UNSUPPORTED (saw {genome_version}, need 'hg19' or 'hg38'). If -sc/--show_centromeres is set, this command requires -V/--refversion indicating the reference genome version.")

    generate_1D2D_plots(
        bbc = pd.read_table(args['input']),
        fcn_lim = (args['minfcn'], args['maxfcn']),
        baf_lim = (args['minbaf'], args['maxbaf']),
        by_sample = args['bysample'],
        outdir = args['outdir'],
        # dummy variables
        genome_version = genome_version,
        title = title,
        show_centromeres = show_centromeres,
        resample_balanced = resample_balanced,
    )

def generate_1D2D_plots(bbc, genome_version, fcn_lim = None, 
                   baf_lim = None, title = None, show_centromeres = False,
                  by_sample = False, outdir = None, resample_balanced = False):
    
    if '#CHR' not in bbc:
        # throw HATCHet error
        raise ValueError('Input table is malformed (missing #CHR column)')
    
    # Prepend 'chr' to #CHR column if not already present
    using_chr = [str(a).startswith('chr') for a in bbc['#CHR'].unique()]
    if any(using_chr):
        if not all(using_chr):
            raise ValueError(sp.error("Some chromosomes use 'chr' notation while others do not."))
        use_chr = True
    else:
        use_chr = False
    if not use_chr:
        bbc = bbc.copy()
        bbc['#CHR'] = 'chr' + bbc['#CHR'].astype('str')
    
    ### code below assumes that chromosomes in BBC table are named with prefix 'chr' ###
    chrlengths = {str(c):df.END.max() for c, df in bbc.groupby('#CHR')}
    chr_ends = [0]
    for i in range(22):
        chr_ends.append(chr_ends[-1] + chrlengths[f'chr{i + 1}'])
  
    n_clones = max([i for i in range(5) if f'cn_clone{i}' in bbc.columns])
    _, mapping = reindex([k for k, _ in bbc.groupby([f'cn_clone{i + 1}' for i in range(n_clones)])])

    if show_centromeres:
        with path(hatchet.resources, f'{genome_version}.centromeres.txt') as centromeres_file:
            centromeres = pd.read_table(centromeres_file, header = None, 
                                        names = ['CHR', 'START', 'END', 'NAME', 'gieStain'])
        chr2centro = {}
        for ch in centromeres.CHR.unique():
            my_df = centromeres[centromeres.CHR == ch]
            assert (my_df.gieStain == 'acen').all()
            # Each centromere should consist of 2 adjacent segments
            assert len(my_df == 2)
            assert my_df.START.max() == my_df.END.min()
            if use_chr:
                if ch.startswith('chr'):
                    chr2centro[ch] = my_df.START.min(), my_df.END.max()
                else:
                    chr2centro['chr' + ch] = my_df.START.min(), my_df.END.max()
            else:
                if ch.startswith('chr'):
                    chr2centro[ch[3:]] = my_df.START.min(), my_df.END.max()
                else:
                    chr2centro[ch] 
    else:
        chr2centro = None
                
    if resample_balanced:
        # Reflect BAF about 0.5 w.p. 0.5 for clusters where all clones are balanced
        bbc = bbc.copy()
        pt = pd.concat([bbc[f'cn_clone{i}'].str.split('|', expand = True) 
                        for i in range(1, n_clones + 1)], axis = 1)
        
        balanced_indices = (pt[0].to_numpy() == pt[1].to_numpy())

        if n_clones > 1:
            balanced_indices = balanced_indices.all(axis = 1)

            np.random.seed(0)
            flips = np.random.randint(2, size = np.count_nonzero(balanced_indices))
            bbc.loc[balanced_indices, 'BAF'] = np.choose(flips, [bbc.loc[balanced_indices, 'BAF'],
                                                                1-bbc.loc[balanced_indices, 'BAF']])

    sp.log("Plotting copy-number states in 2D\n", level = 'INFO')
    if by_sample:
        plot_clusters(bbc, mapping, xlim = baf_lim, ylim = fcn_lim, dpi = 300,
                     save_samples = True, save_prefix = os.path.join(outdir, '2D'))
    else:
        plot_clusters(bbc, mapping, xlim = baf_lim, ylim = fcn_lim, dpi = 300,
        fname = os.path.join(outdir, '2D-plot.png'))
    
    sp.log("Plotting copy-number segments in 1D along the genome\n", level = 'INFO')
    if by_sample:
        plot_genome(bbc, mapping, chr_ends, chr2centro, show_centromeres = show_centromeres,
                baf_ylim = baf_lim, fcn_ylim = fcn_lim, 
                    save_samples = True, save_prefix = os.path.join(outdir, '1D'))        
    else:
        plot_genome(bbc, mapping, chr_ends, chr2centro, show_centromeres = show_centromeres,
                baf_ylim = baf_lim, fcn_ylim = fcn_lim, fname = os.path.join(outdir, '1D-plot.png'))
    
    sp.log("Done\n", level = 'INFO')


def plot_genome(big_bbc, mapping, chr_ends, chr2centro, chromosomes = None, dpi = 400, 
                figsize = (8, 5), fname = None, 
                show_centromeres = False, fcn_ylim = None, baf_ylim = None,
               save_samples = False, save_prefix = None): 
    if save_samples:
        if save_prefix is None:
            raise ValueError("If save_samples=True, 1D plotting requires filename prefix in [save_prefix] but found [None].")
    
    colors1 = plt.cm.tab20b(np.arange(20))
    colors2 = plt.cm.tab20c(np.arange(20))

    # combine them and build a new colormap
    colors = np.vstack((colors1, colors2))
    cmap = mcolors.LinearSegmentedColormap.from_list('my_colormap', colors)

    big_bbc = big_bbc.copy()
    np.random.seed(0)
    flips = np.random.randint(2, size = len(big_bbc))
    big_bbc.loc[:, 'BAF'] = np.choose(flips, 
                                      [big_bbc.loc[:, 'BAF'], 1-big_bbc.loc[:, 'BAF']])

    
    samples = big_bbc.SAMPLE.unique()
    
    if save_samples:
        fig, axes = plt.subplots(2, dpi = dpi, figsize =figsize)
    else:
        fig, axes = plt.subplots(2*len(samples), dpi = dpi, figsize=(8 * figsize[0],
        int(len(samples)*figsize[1])))

    n_states = len(mapping)
    mapping = mapping.copy()
    
    n_bins = len(big_bbc) / len(samples)
    
    # markersize decreases from 4 at 1-500 bins to 1 at >1500 bins
    markersize = int(max(1, 4 - np.floor(n_bins / 500)))
    
    if n_states <= 20:
        cmap = plt.get_cmap('tab20')
        mapping = {k:v%20 for k,v in mapping.items()}
        
    else:
        colors1 = plt.cm.tab20b(np.arange(20))
        colors2 = plt.cm.tab20c(np.arange(20))

        # combine them and build a new colormap
        colors = np.vstack((colors1, colors2))
        cmap = mcolors.LinearSegmentedColormap.from_list('my_colormap', colors)
        mapping = {k:v%40 / n_states for k,v in mapping.items()}

    for idx,sample in enumerate(samples):
        if save_samples:
            # Ignore the sample index and write on first 2 axes
            idx = 0
    
        bbc_ = big_bbc[big_bbc.SAMPLE == sample]
        bbc_ = bbc_.reset_index(drop=True)

        if chromosomes is None:
            #chromosomes = sorted(big_bbc['#CHR'].unique(), key = lambda x: int(x[3:]))
            # WARNING: THIS WILL PUT CHROMOSOMES OUT OF ORDER IF USING 'chr' NOTATION
            chromosomes = sorted(bbc_['#CHR'].unique())
            
        n_clones = max([i for i in range(5) if f'cn_clone{i}' in bbc_.columns])
        props = np.array([bbc_.iloc[0, 2 * i + 12] for i in range(n_clones + 1)]).round(6)
        n_clones2, gamma = compute_gamma(bbc_)
        assert n_clones2 == n_clones
        
        #fig, axes = plt.subplots(2, 1, dpi = dpi, figsize = figsize)

        if limits_valid(fcn_ylim):
            minFCN, maxFCN = fcn_ylim
        else:
            minFCN = np.min(bbc_.RD * gamma)
            maxFCN = np.max(bbc_.RD * gamma)
            
        if limits_valid(baf_ylim):
            minBAF, maxBAF = baf_ylim
        else:
            minBAF = np.min(bbc_.BAF)
            maxBAF = np.max(bbc_.BAF)
        
        FCNrange = maxFCN - minFCN
        BAFrange = maxBAF - minBAF
        
        chrkey = 'CHR' if 'CHR' in bbc_.columns else '#CHR'
        
        for chromosome in chromosomes:
            bbc = bbc_[bbc_[chrkey] == chromosome]
            chr_start = chr_ends[int(chromosome[3:]) - 1]
            
            flag = bbc['#CHR'] == chromosome
            bbc = bbc[flag]

            my_rows = np.where(flag)[0]

            offset = bbc.END.max()
            midpoint = np.mean(np.array([bbc.START, bbc.END]), axis = 0) + chr_start

            # Add black bars indicating 
            fcn_lines = []
            baf_lines = []
            colors = []
            for _, r in bbc.iterrows():
                x0 = r.START + chr_start
                x1 = r.END + chr_start
                state = [(1,1)] + [str2state(r[f'cn_clone{i + 1}']) for i in range(n_clones)]
                y_fcn, y_baf = cn2evs(state, props)
                fcn_lines.append([(x0, y_fcn), (x1, y_fcn)])
                baf_lines.append([(x0, y_baf), (x1, y_baf)])
                baf_lines.append([(x0, 1-y_baf), (x1, 1-y_baf)])

                colors.append((0, 0, 0, 1))

            lc_fcn = collections.LineCollection(fcn_lines, linewidth = 2, colors = colors)
            axes[idx*2+0].add_collection(lc_fcn)
            lc_baf = collections.LineCollection(baf_lines, linewidth = 2, colors = colors)
            axes[idx*2+1].add_collection(lc_baf)

            if show_centromeres:
                centro = chr2centro['chr'+str(chromosome)]
                axes[idx*2+0].add_patch(Rectangle((centro[0] + chr_start, minFCN - 0.1), 
                                            centro[1] - centro[0], maxFCN - minFCN + 0.2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                axes[idx*2+1].add_patch(Rectangle((centro[0] + chr_start, minBAF - 0.02), 
                                            centro[1] - centro[0], 0.52 - minBAF + 0.02, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                """
                # Try plotting centromeres that only occupy the middle 50% of the y-range
                # (to avoid confusing centromeres with chromosome thresholds)
                axes[idx*2+0].add_patch(Rectangle((centro[0] + chr_start, minFCN - 0.1 + FCNrange/4), 
                                            centro[1] - centro[0], maxFCN - minFCN - FCNrange/2 + 0.2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                axes[idx*2+1].add_patch(Rectangle((centro[0] + chr_start, minBAF - 0.02 + BAFrange/4), 
                                            centro[1] - centro[0], 0.52 - minBAF + 0.02 - BAFrange/2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                """

            if n_clones == 1:
                my_colors = [cmap(mapping[r]) for r in bbc.cn_clone1]
            else:
                my_colors = [cmap(mapping[tuple(r)]) for _, r in bbc[[f'cn_clone{i + 1}' for i in range(n_clones)]].iterrows()]

            axes[idx*2+0].scatter(midpoint, bbc.RD * gamma, s = markersize, alpha = 1, c = my_colors)
            axes[idx*2+1].scatter(midpoint, bbc.BAF, s = markersize, alpha = 1, c = my_colors)


        if limits_valid(fcn_ylim):
            axes[idx*2+0].set_ylim(fcn_ylim)
        else:
            axes[idx*2+0].set_ylim([minFCN - 0.1, maxFCN + 0.1])
        
        axes[idx*2+0].set_xlim([0, chr_ends[-1]])
        axes[idx*2+0].set_ylabel("Fractional Copy Number")

        if limits_valid(baf_ylim):
            axes[idx*2+1].set_ylim(baf_ylim)
        else:
            axes[idx*2+1].set_ylim([minBAF - 0.02, (1-minBAF) + 0.02])
        
        axes[idx*2+1].set_xlim([0, chr_ends[-1]])
        axes[idx*2+1].set_ylabel("B-allele Frequency")
        
        axes[idx*2+0].vlines(chr_ends[1:-1], minFCN - 0.1, maxFCN + 0.1, 
                             linewidth = 0.5, colors = 'k')
        axes[idx*2+1].vlines(chr_ends[1:-1], minBAF - 0.02, (1-minBAF) + 0.02, 
                             linewidth = 0.5, colors = 'k')

        xtick_labels = [f'chr{i}' for i in range(1, 23)]
        xtick_locs = [(chr_ends[i] + chr_ends[i + 1]) / 2 for i in range(22)]
        axes[idx*2+0].set_xticks(xtick_locs)
        axes[idx*2+0].set_xticklabels(xtick_labels)
        axes[idx*2+0].tick_params(axis='x', rotation=70)
        axes[idx*2+1].set_xticks(xtick_locs)
        axes[idx*2+1].set_xticklabels(xtick_labels)
        axes[idx*2+1].tick_params(axis='x', rotation=70)
    
        axes[idx*2+0].title.set_text(f'Sample: {sample}')        
        axes[idx*2+1].title.set_text(f'Sample: {sample}')     
        
        plt.tight_layout()
        if not save_samples and fname is not None:
            plt.savefig(fname)
            plt.close()

def limits_valid(lim):
    return lim is not None and len(lim) == 2 and lim[0] is not None and lim[1] is not None

def recompose_state(l):
    """
    Read copy-number state vector from list of allele-specific values
    """
    r = []
    for i in range(int(len(l) / 2)):
        r.append((int(l[i * 2]), int(l[i * 2 + 1])))
    return tuple(r)

str2cn = lambda x: tuple([int(a) for a in x.split('|')])
cn2totals = lambda x: tuple(sum(a) for a in x)
str2state = lambda cn: tuple([int(a) for a in cn.split('|')])

def reindex(labels):
    """
    Given a list of labels, reindex them as integers from 1 to n_labels
    Labels are in nonincreasing order of prevalence
    """
    old2new = {}
    j = 1
    for i, _ in Counter(labels).most_common():
        old2new[i] = j
        j += 1
    old2newf = lambda x: old2new[x]

    return [old2newf(a) for a in labels], old2new

def cn2total(s):
    tkns = s.split('|')
    assert len(tkns) == 2
    return int(tkns[0]) + int(tkns[1])

def compute_gamma(bbc):
    bbc = bbc.reset_index(drop = True)
    n_clones = int((len(bbc.columns) - 13) / 2)
    bbc['fractional_cn'] = sum([bbc.iloc[:, 11 + 2*i].map(cn2total) * bbc.iloc[:, 12 + 2*i] for i in range(n_clones + 1)])
    largest_clone = np.argmax([bbc['u_clone{}'.format(i + 1)][0] for i in range(n_clones)])
    dominant_cns = Counter(bbc['cn_clone{}'.format(largest_clone + 1)])
    balanced_options = set(['1|1', '2|2', '3|3', '4|4'])
    largest_balanced = max(balanced_options, key = lambda x: dominant_cns[x])
    balanced_idx = [i for i in range(len(bbc)) if 
                    all([bbc['cn_clone{}'.format(j + 1)][i] == largest_balanced for j in range(n_clones)])
                   and bbc.loc[i, 'RD'] > 0]
    if len(balanced_idx) == 0:
        balanced_options.remove(largest_balanced)
        largest_balanced = max(balanced_options, key = lambda x: dominant_cns[x])
        balanced_idx = [i for i in range(len(bbc)) if 
                    all([bbc['cn_clone{}'.format(j + 1)][i] == largest_balanced for j in range(n_clones)])
                       and bbc.loc[i, 'RD'] > 0]
        
    #print("Computing gamma using {} balanced bins across all {} clones".format(len(balanced_idx), n_clones))
    return n_clones, np.mean(bbc.iloc[balanced_idx].fractional_cn / bbc.iloc[balanced_idx].RD)

def cn2evs(cns, props):
    assert len(cns) == len(props)
    A = np.array([x[0] for x in cns])
    B = np.array([x[1] for x in cns])
    
    return np.sum((A + B) * props), np.sum(B * props) / np.sum((A+B) * props)

def plot_genome(big_bbc, mapping, chr_ends, chr2centro, chromosomes = None, dpi = 400, 
                figsize = (8, 5), fname = None, 
                show_centromeres = False, fcn_ylim = None, baf_ylim = None,
               save_samples = False, save_prefix = None): 
    if save_samples:
        if save_prefix is None:
            raise ValueError("If save_samples=True, 1D plotting requires filename prefix in [save_prefix] but found [None].")
    
    big_bbc = big_bbc.copy()
    np.random.seed(0)
    flips = np.random.randint(2, size = len(big_bbc))
    big_bbc.loc[:, 'BAF'] = np.choose(flips, 
                                      [big_bbc.loc[:, 'BAF'], 1-big_bbc.loc[:, 'BAF']])

    colors1 = plt.cm.tab20b(np.arange(20))
    colors2 = plt.cm.tab20c(np.arange(20))

    # combine them and build a new colormap
    colors = np.vstack((colors1, colors2))
    cmap = mcolors.LinearSegmentedColormap.from_list('my_colormap', colors)

    samples = big_bbc.SAMPLE.unique()
    
    if save_samples:
        fig, axes = plt.subplots(2, dpi = dpi, figsize = figsize)
    else:
        fig, axes = plt.subplots(2*len(samples), dpi = dpi, figsize=(figsize[0],int(len(samples)*figsize[1])))

    n_states = len(mapping)
    mapping = mapping.copy()
    
    n_bins = len(big_bbc) / len(samples)
    
    # markersize decreases from 4 at 1-500 bins to 1 at >1500 bins
    markersize = int(max(1, 4 - np.floor(n_bins / 500)))
    
    if n_states <= 20:
        cmap = plt.get_cmap('tab20')
        mapping = {k:v%20 for k,v in mapping.items()}
        
    else:
        colors1 = plt.cm.tab20b(np.arange(20))
        colors2 = plt.cm.tab20c(np.arange(20))

        # combine them and build a new colormap
        colors = np.vstack((colors1, colors2))
        cmap = mcolors.LinearSegmentedColormap.from_list('my_colormap', colors)
        mapping = {k:v%40 / n_states for k,v in mapping.items()}

    for idx,sample in enumerate(samples):
        if save_samples:
            # Ignore the sample index and write on first 2 axes
            idx = 0
    
        bbc_ = big_bbc[big_bbc.SAMPLE == sample]
        bbc_ = bbc_.reset_index(drop=True)

        if chromosomes is None:
            #chromosomes = sorted(big_bbc['#CHR'].unique(), key = lambda x: int(x[3:]))
            # WARNING: THIS WILL PUT CHROMOSOMES OUT OF ORDER IF USING 'chr' NOTATION
            chromosomes = sorted(bbc_['#CHR'].unique())
            
        n_clones = max([i for i in range(5) if f'cn_clone{i}' in bbc_.columns])
        props = np.array([bbc_.iloc[0, 2 * i + 12] for i in range(n_clones + 1)]).round(6)
        n_clones2, gamma = compute_gamma(bbc_)
        assert n_clones2 == n_clones
        
        #fig, axes = plt.subplots(2, 1, dpi = dpi, figsize = figsize)

        if limits_valid(fcn_ylim):
            minFCN, maxFCN = fcn_ylim
        else:
            minFCN = np.min(bbc_.RD * gamma)
            maxFCN = np.max(bbc_.RD * gamma)
            
        if limits_valid(baf_ylim):
            minBAF, maxBAF = baf_ylim
        else:
            minBAF = np.min(bbc_.BAF)
            maxBAF = np.max(bbc_.BAF)
        
        FCNrange = maxFCN - minFCN
        BAFrange = maxBAF - minBAF
        
        chrkey = 'CHR' if 'CHR' in bbc_.columns else '#CHR'
        
        for chromosome in chromosomes:
            bbc = bbc_[bbc_[chrkey] == chromosome]
            chr_start = chr_ends[int(chromosome[3:]) - 1]
            
            flag = bbc['#CHR'] == chromosome
            bbc = bbc[flag]

            my_rows = np.where(flag)[0]

            offset = bbc.END.max()
            midpoint = np.mean(np.array([bbc.START, bbc.END]), axis = 0) + chr_start

            # Add black bars indicating 
            fcn_lines = []
            baf_lines = []
            colors = []
            for _, r in bbc.iterrows():
                x0 = r.START + chr_start
                x1 = r.END + chr_start
                state = [(1,1)] + [str2state(r[f'cn_clone{i + 1}']) for i in range(n_clones)]
                y_fcn, y_baf = cn2evs(state, props)
                fcn_lines.append([(x0, y_fcn), (x1, y_fcn)])
                baf_lines.append([(x0, y_baf), (x1, y_baf)])
                baf_lines.append([(x0, 1-y_baf), (x1, 1-y_baf)])

                colors.append((0, 0, 0, 1))

            lc_fcn = collections.LineCollection(fcn_lines, linewidth = 2, colors = colors)
            axes[idx*2+0].add_collection(lc_fcn)
            lc_baf = collections.LineCollection(baf_lines, linewidth = 2, colors = colors)
            axes[idx*2+1].add_collection(lc_baf)

            if show_centromeres:
                centro = chr2centro['chr'+str(chromosome)]
                axes[idx*2+0].add_patch(Rectangle((centro[0] + chr_start, minFCN - 0.1), 
                                            centro[1] - centro[0], maxFCN - minFCN + 0.2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                axes[idx*2+1].add_patch(Rectangle((centro[0] + chr_start, minBAF - 0.02), 
                                            centro[1] - centro[0], 0.52 - minBAF + 0.02, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                """
                # Try plotting centromeres that only occupy the middle 50% of the y-range
                # (to avoid confusing centromeres with chromosome thresholds)
                axes[idx*2+0].add_patch(Rectangle((centro[0] + chr_start, minFCN - 0.1 + FCNrange/4), 
                                            centro[1] - centro[0], maxFCN - minFCN - FCNrange/2 + 0.2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                axes[idx*2+1].add_patch(Rectangle((centro[0] + chr_start, minBAF - 0.02 + BAFrange/4), 
                                            centro[1] - centro[0], 0.52 - minBAF + 0.02 - BAFrange/2, 
                                            linewidth = 0, color = (0, 0, 0, 0.4)))
                """

            if n_clones == 1:
                my_colors = [cmap(mapping[r]) for r in bbc.cn_clone1]
            else:
                my_colors = [cmap(mapping[tuple(r)]) for _, r in bbc[[f'cn_clone{i + 1}' for i in range(n_clones)]].iterrows()]

            axes[idx*2+0].scatter(midpoint, bbc.RD * gamma, s = markersize, alpha = 1, c = my_colors)
            axes[idx*2+1].scatter(midpoint, bbc.BAF, s = markersize, alpha = 1, c = my_colors)


        if limits_valid(fcn_ylim):
            axes[idx*2+0].set_ylim(fcn_ylim)
        else:
            axes[idx*2+0].set_ylim([minFCN - 0.1, maxFCN + 0.1])
        
        axes[idx*2+0].set_xlim([0, chr_ends[-1]])
        axes[idx*2+0].set_ylabel("Fractional Copy Number")

        if limits_valid(baf_ylim):
            axes[idx*2+1].set_ylim(baf_ylim)
        else:
            axes[idx*2+1].set_ylim([minBAF - 0.02, (1-minBAF) + 0.02])
        
        axes[idx*2+1].set_xlim([0, chr_ends[-1]])
        axes[idx*2+1].set_ylabel("B-allele Frequency")
        
        axes[idx*2+0].vlines(chr_ends[1:-1], minFCN - 0.1, maxFCN + 0.1, 
                             linewidth = 0.5, colors = 'k')
        axes[idx*2+1].vlines(chr_ends[1:-1], minBAF - 0.02, (1-minBAF) + 0.02, 
                             linewidth = 0.5, colors = 'k')

        xtick_labels = [f'chr{i}' for i in range(1, 23)]
        xtick_locs = [(chr_ends[i] + chr_ends[i + 1]) / 2 for i in range(22)]
        axes[idx*2+0].set_xticks(xtick_locs)
        axes[idx*2+0].set_xticklabels(xtick_labels)
        axes[idx*2+0].tick_params(axis='x', rotation=70)
        axes[idx*2+1].set_xticks(xtick_locs)
        axes[idx*2+1].set_xticklabels(xtick_labels)
        axes[idx*2+1].tick_params(axis='x', rotation=70)
    
        axes[idx*2+0].title.set_text(f'Sample: {sample}')        
        axes[idx*2+1].title.set_text(f'Sample: {sample}')     
        
        if save_samples:
            plt.tight_layout()
            plt.savefig(f'{save_prefix}_{sample}.png')
            plt.close()
            fig, axes = plt.subplots(2, dpi = dpi, figsize = figsize)


    if not save_samples and fname is not None:
        plt.tight_layout()
        plt.savefig(fname)

    plt.close()

def plot_clusters(bbc, mapping, figsize = (4,4), fname = None, 
                  dpi = 300, xlim = None, ylim = None,
                 save_samples = False, save_prefix = None):
    if save_samples:
        if save_prefix is None:
            raise ValueError("If save_samples=True, 2D plotting requires filename prefix in [save_prefix] but found [None].")
    
    samples = bbc.SAMPLE.unique()
    if save_samples:
        fig, axs = plt.subplots(figsize=figsize)
    else:
        fig, axs = plt.subplots(len(samples), figsize=(figsize[0],int(len(samples)*figsize[1])))
   
    n_states = len(mapping)
    mapping = mapping.copy()
    
    if n_states <= 20:
        cmap = plt.get_cmap('tab20')
        mapping = {k:v%20 for k,v in mapping.items()}
        
    else:
        colors1 = plt.cm.tab20b(np.arange(20))
        colors2 = plt.cm.tab20c(np.arange(20))

        # combine them and build a new colormap
        colors = np.vstack((colors1, colors2))
        cmap = mcolors.LinearSegmentedColormap.from_list('my_colormap', colors)
        
        # incorporate normalization in mapping
        mapping = {k:v%40 / n_states for k,v in mapping.items()}


    for idx,sample in enumerate(samples):
        my_ax = axs[idx] if len(samples) > 1 and not save_samples else axs
        
        bbc_ = bbc[bbc.SAMPLE == sample]
        bbc_ = bbc_.reset_index(drop=True)

        n_clones = max([i for i in range(5) if f'cn_clone{i}' in bbc_.columns])
        props = np.array([bbc_.iloc[0, 2 * i + 12] for i in range(n_clones + 1)]).round(6)
        n_clones2, gamma = compute_gamma(bbc_)
        assert n_clones2 == n_clones

        if n_clones == 1:
            my_colors = [cmap(mapping[r]) for r in bbc_.cn_clone1]
        else:
            my_colors = [cmap(mapping[tuple(r)]) for _, r in bbc_[[f'cn_clone{i + 1}' for i in range(n_clones)]].iterrows()]
        
        my_ax.scatter(bbc_.BAF, bbc_.RD * gamma, c = my_colors, s = 1)         

        exs = []
        eys = []
        cs = []
        for k, _ in bbc_.groupby([f'cn_clone{i + 1}' for i in range(n_clones)]):
            if type(k) == str:
                state = [(1,1), str2state(k)]
            else:
                state = [(1,1)] + [str2state(a) for a in k]
            ey, ex = cn2evs(state, props)
            if all([a == state[1] for a in state[1:]]) and n_clones > 1:
                my_ax.annotate(f'{str(state[1])} ', (ex, ey), fontsize = 'x-small', 
                               fontweight = 'bold', ha = 'right', va = 'center')
            else:
                my_ax.annotate(f'{",".join([str(a) for a in state[1:]])} ', (ex, ey), 
                               fontsize = 'x-small', ha = 'right', va = 'center')
            exs.append(ex)
            eys.append(ey)
            cs.append(cmap(mapping[k]))
        
        my_ax.scatter(exs, eys, s = 10, c = cs, edgecolor = 'k', linewidth = 0.8)            
        
        legendstr = []
        for i in range(n_clones + 1):
            if i == 0:
                legendstr.append('Normal: {:.3f}'.format(bbc_.u_normal[0]))
            else:
                legendstr.append('Clone {}: {:.3f}'.format(i, bbc_['u_clone{}'.format(i)][0]))

        handles = [Rectangle((0, 0), 1, 1, fc="white", ec="white", 
                                         lw=0, alpha=0)]     
        my_ax.legend(handles, ["\n".join(legendstr)], loc='best', fontsize='small', 
                  fancybox=True, framealpha=0.7, 
                  handlelength=0, handletextpad=0)
        
        if len(samples) > 1:
            my_ax.set_title(sample)
            

        if limits_valid(xlim):
            my_ax.set_xlim(xlim)
        else:
            xmin, xmax = my_ax.get_xlim()
            
        if limits_valid(ylim):
            my_ax.set_ylim(ylim)
            ymin, ymax = ylim
        else:
            ymin, ymax = my_ax.get_ylim()
                        
        my_ax.vlines(ymin = ymin, ymax = ymax, x = 0.5, linestyle = ':',
                         linewidth = 1, colors = 'grey')            
            
    
        my_ax.set_ylabel("Fractional Copy Number") 
        if idx == len(samples)-1 or save_samples:
            my_ax.set_xlabel("Mirrored BAF") 
            
        if save_samples:
            plt.tight_layout()
            plt.title(sample)
            plt.savefig(f'{save_prefix}_{sample}.png')
            plt.close()
            fig, axs = plt.subplots(figsize=figsize)

    if fname is not None and not save_samples:
        plt.tight_layout()
        plt.savefig(fname)

    plt.close()

if __name__ == '__main__':
        main()
