import pickle
import os
import networkx as nx
import pandas as pd
import prody
import numpy as np
import igraph
from tqdm import tqdm

from .visualize.visualize import plot_collectivity,plot_correlation_density,plot_network_spring,plot_scatter,plot_vector,heatmap_annotated, plot_fiedler_data
#from .utilities import *


class Enm():
    """This object is wrapper around prody GNM object and networkx analysis
    """

    def __init__(self, name):
        """Constructor

        :param name: name of the object for future reference, can be arbitrary
        :type name: string"""
        self.name = name
        self.figure_path = "../reports/figures/"
        self.output_path = "../data/interim/"
        self.rewired = False
        self.rewire_df = None
        self.arr = None
        self.e_list = None
        self.df = None
        self.G = None
        self.graph_gc = None
        self.nodes=None
        self.degree = None
        self.gnm = None
        self.coll=None
        self.coll_index_sorted = None
        self.prs_mat = None
        self.L = None

    def print_name(self):
        """This prints name variable
        """
        print(self.name)

    def spring_pos(self):
        """Create spring layout of the giant component network and assign positions to nodes
        """
        try:
            pos = nx.spring_layout(self.graph_gc, k=0.6,
                                   scale=4, iterations=200)
            nx.set_node_attributes(self.graph_gc, pos, 'pos')
        except AttributeError:
            raise(
                'Giant component is not set yet. First call read network or giant component')

    def read_network(self, path, **kwargs):
        """Read network file and assign it to object

        :param path: Network file path
        :type path: string

        """
        sep = kwargs.pop('sep', None)
        _, ext = os.path.splitext(path)
        # return fname, ext
        if ext == '.csv' or sep == ',':
            nw_read = pd.read_csv(path)
            # Create network ##########
            G = nx.from_pandas_edgelist(
                nw_read, source='gene1', target='gene2')
        elif ext == '.gpickle':
            G = nx.read_gpickle(path)
        elif ext == '.tsv' or sep == '\t':
            nw_read = pd.read_csv(path, sep='\t')
            # Create network ##########
            G = nx.from_pandas_edgelist(
                nw_read, source='gene1', target='gene2')
        elif ext == '.gml':
            G = nx.read_gml(path)
        self.G = G
        self.giant_component()

    def giant_component(self):
        """From the graph variable create giant component and assing nodes and degree to Enm object
        """

        Gc = max([self.G.subgraph(c).copy()
                  for c in nx.connected_components(self.G)], key=len)
        self.graph_gc = Gc
        nodes = [_ for _ in self.graph_gc.nodes()]
        self.nodes = nodes
        degree = [deg for id, deg in list(self.graph_gc.degree)]
        self.degree = degree

    def laplacian_matrix(self, normalized=False,**kwargs):
        """get Laplacian matrix of the giant component. Wrapper around networkx.laplacian_matrix
        """
        if normalized:
            self.L = nx.normalized_laplacian_matrix(self.graph_gc,weight=None).todense()
        else:
            self.L = nx.laplacian_matrix(self.graph_gc, weight=None).todense()

    def get_gnm(self, **kwargs):
        """Calculate GNM modes and collectivity values
        """
        if self.L is None:
            self.laplacian_matrix(**kwargs)
        gnm = prody.GNM()
        gnm.setKirchhoff(self.L)

        gnm.calcModes(n_modes=None, zeros=False)
        #gnm.nodes = nodes
        #gnm.degrees = degree
        self.gnm = gnm
        # showCrossCorr(gnm)
        #sqf_orig = prody.calcSqFlucts(self.gnm)
        coll = prody.calcCollectivity(self.gnm)
        self.coll = coll
        coll_index_sorted = sorted(
            range(len(self.coll)), key=lambda k: self.coll[k], reverse=True)

        self.coll_index_sorted = coll_index_sorted

    def get_prs(self,**kwargs):
        """Calculate Perturbation response matrix
        """
        try:
            no_diag = kwargs.pop('no_diag','True')
            prs_mat, _, _ = prody.calcPerturbResponse(
                self.gnm, no_diag=no_diag)
        except Exception as e:
            raise AttributeError('GNM is not calculated yet. Call get_gnm() first')
        self.prs_mat = prs_mat

    def create_df(self):
        """Create an overall dataframe to store network related and GNM related values
        """
        df = pd.DataFrame()
        df['orf_name'] = self.nodes
        df['deg'] = self.degree
        eff_orig = np.sum(self.prs_mat, axis=1)
        sens_orig = np.sum(self.prs_mat, axis=0)
        eigvecs_df = pd.DataFrame(self.gnm.getEigvecs(
        )[:, self.coll_index_sorted[:8]], columns=[f'eig_{i}' for i in range(8)])

        df_ = pd.merge(df, eigvecs_df, left_index=True, right_index=True)
        df_['eff'] = eff_orig
        df_['sens'] = sens_orig
        eigenvector_centr = nx.eigenvector_centrality_numpy(self.graph_gc)
        closeness_centr = nx.closeness_centrality(self.graph_gc)
        df_['btw'] = betweenness_nx(self.graph_gc, normalized=True)
        df_['trans'] = list((nx.clustering(self.graph_gc)).values())
        df_['eigenvec_centr'] = [eigenvector_centr[i]
                                 for i in eigenvector_centr]
        df_['closeness_centr'] = [closeness_centr[i] for i in closeness_centr]
        df_['smallest_eigenvec'] = self.gnm.getEigvecs()[:, 0]
        self.df = df_

    def fiedler_evaluation(self, figure_name = "lost_edges_node_counts", figure_extension = 'png', plot=False, **kwargs):
        """This function evaluates fiedler vector cut. Using eigenvectors of Laplacian, calculates 2 subnetworks and return
        the number of edges lost between 2 subnetworks with the cut and number of nodes in the smaller subnetwork
        """
        gc = self.graph_gc
        eigvecs = self.gnm.getEigvecs()
        orf_names = self.df.orf_name
        lost_edges = [ ]
        adj = nx.adjacency_matrix(gc).todense()
        orf_names = self.df.orf_name
        g_ig = igraph.Graph.Adjacency((adj > 0).tolist(), "UNDIRECTED")
        g_ig.vs['name'] = orf_names

        for i in tqdm(range(len(gc.nodes)-1)):
            cl1 = [orf_names[i] for i, j in enumerate(eigvecs[:,i]) if j>0]
            cl2 = [orf_names[i] for i, j in enumerate(eigvecs[:,i]) if j<0]
            cg1 = g_ig.induced_subgraph(cl1)
            cg2 = g_ig.induced_subgraph(cl2)
            #cg1 = nx.induced_subgraph(gc, cl1)
            #cg2 = nx.induced_subgraph(gc,cl2)
            #lost_edges.append( len(gc.edges)-(len(cg2.edges)+len(cg1.edges)))
            lost_edges.append( len(gc.edges)-(len(cg2.es)+len(cg1.es)))

        node_counts_c1 = np.minimum(np.count_nonzero(eigvecs>0, axis=0),np.count_nonzero(eigvecs<0, axis=0))
        node_counts_c2 = np.maximum(np.count_nonzero(eigvecs>0, axis=0),np.count_nonzero(eigvecs<0, axis=0))
#        data = {'lost_edges':lost_edges, 'node_counts_c1':node_counts_c1}
        self.lost_edges =  lost_edges#data
        self.node_counts_c1 = node_counts_c1
        if plot:
            plot_fiedler_data(self, figure_name= figure_name, figure_extension=figure_extension)


    def gnm_analysis(self, **kwargs):
        """Wrapper to run gnm, prs and create_df
        """
        self.get_gnm(**kwargs)
        self.get_prs(**kwargs)
        self.create_df()

    def get_category(self, strain_ids_df_file):
        """ Uses costanzo strain id file to determine categories. File is created by pgsNetwork project earlier
            
        """
        strain_ids = pd.read_csv(strain_ids_df_file)
        combined_df = pd.merge(self.df, strain_ids, left_on='orf_name',right_on='Allele Gene name')
        combined_df['group']=np.where(combined_df.cat.isna(),'essential','nonessential')
        combined_df = combined_df.fillna({'cat':'essential'})
        cat_change_dict = {'essential': 'Essential',
                  'na.nq.nxes':'Nonessential\nquery and array',
                  'nxes.only':'Nonessential \nquery crossed \n with Essential',
                  'nq.nxes':'Nonessential query',
                  'na.nq':'Nonessential\nquery and array',
                  'na.nxes':'Nonessential\nquery and array',
                  'nq.only':'Nonessential query',
                  'na.only':'Nonessential array'}
        combined_df['cat_']= combined_df['cat'].map(cat_change_dict)
        self.df = combined_df
        #db_connection_str = 'mysql+pymysql://oma21:dktgp2750@localhost:3306/ANNE'
        #db_connection = sql.create_engine(db_connection_str)
        #db_df = pd.read_sql('SELECT * FROM SUMMARY_2012', con=db_connection)
        #combined_df = pd.merge(combined_df, db_df, left_on='Systematic gene name', right_on='orf_name')
    def get_node_distances(self):
        dist_to_center = {}
        if len(nx.get_node_attributes(self.graph_gc, 'pos')) == 0:
            self.spring_pos()

        pos = self.graph_gc.nodes('pos')
        for i,val_i in enumerate(self.nodes):
            dist_to_center[val_i]=np.linalg.norm(pos[val_i])
        self.dist_to_center = dist_to_center
    def plot_network_spring(self, **kwargs):
        """Plot network with spring layout
        """
        Gc = self.graph_gc
        if nx.get_node_attributes(Gc, 'pos') == {}:
            self.spring_pos()

        return plot_network_spring(Gc, self.figure_path, **kwargs)

    def plot_collectivity(self, **kwargs):
        """Plot collectivity values and color most collective modes
        """
        return plot_collectivity(self.coll, self.coll_index_sorted, self.figure_path, **kwargs)

    def plot_scatter(self, x, y, **kwargs):
        """Plot scatter plot of 2 columns in df

        :param x: first variable name
        :type x: string
        :param y: second variable name
        :type y: string
        """
        return plot_scatter(self.df, x, y, self.figure_path, **kwargs)

    def simulate_rewire(self, rewired=False, rewire_df_name=None, arr_name=None, **kwargs):
        """Wrapper around enm.simulate_rewire function out of the class
        """
        output_path = kwargs.pop('output_path', self.output_path) 

        arr, rewire_df, e_list = simulate_rewire(
            self.graph_gc, rewired, rewire_df_name, arr_name, output_path=output_path, **kwargs)
        nodegseq= kwargs.pop('nodegseq',False)
        if nodegseq:
            self.arr_nodegseq = arr
            self.rewire_df_nodegseq = rewire_df
            self.e_list_nodegseq = e_list
        else:
            self.arr = arr
            self.rewire_df = rewire_df
            self.e_list = e_list

        
    def plot_correlation_density(self, x, y, **kwargs):
        """Plot correlation density between x and y. Requires rewire_df

        :param x: first variable name
        :type x: string
        :param y: second variable name
        :type y: string
        """
        try:
            return plot_correlation_density(self.df, self.rewire_df, x, y, self.figure_path, **kwargs)
        except Exception as e:
            raise(AttributeError(
                'Make sure rewire_df is calculated. Call simulate_rewire() first'))

    def heatmap_annotated(self, **kwargs):
        """Plot PRS heatmap with clustering dendrograms
        """
        return heatmap_annotated(self.prs_mat, self.figure_path, **kwargs)

    def plot_vector(self, eigen_id='eig_0', color_id=0, sorted=False, **kwargs):
        data = self.df.loc[:, eigen_id]
        return plot_vector(data, sorted=sorted, figure_path=self.figure_path, color_id=color_id,**kwargs)

    def save(self, **kwargs):
        filename = kwargs.pop('filename', self.name)
        with open(f"../data/interim/{filename}.pickle", 'wb') as handle:
            pickle.dump(self, handle)


def betweenness_ig(g, normalized=False):
    n = g.vcount()
    btw = g.betweenness()

    if normalized:
        norm = [2 * a / (n * n - 3 * n + 2) for a in btw]
        return norm
    else:
        return btw

def igraph_network(g):
    adj = nx.adjacency_matrix(g).todense()
    g_ig = igraph.Graph.Adjacency((adj > 0).tolist(),'UNDIRECTED')
    return g_ig

def betweenness_nx(g, normalized=False):
    g_ig = igraph_network(g)
    return betweenness_ig(g_ig, normalized)


def rewire_network(Gc, **kwargs):
    """This is wrapper around networkx's rewire functions for my purposes. It can rewire by keeping degree, or if not it will generate a network with same number of nodes and arbitrary number of edges using barabasi_albert_graph or erdos_renyi_graph

    :param Gc: Network to be rewired    
    :type Gc: networkx object
    :return: Rewired network
    :rtype: networkx object
    """
    nodegseq = kwargs.pop('nodegseq', False)
    if nodegseq:
        random_network_type = kwargs.pop('random_network_type', 'ba')
        if random_network_type == 'ba':
            Gc_rewired = nx.barabasi_albert_graph(n=len(Gc.nodes), m=7)
        elif random_network_type == 'er':
            Gc_rewired = nx.erdos_renyi_graph(len(Gc.nodes), 0.004)
    else:
        Gc_rewired = Gc.copy()
        swp_count = nx.connected_double_edge_swap(
            Gc_rewired, 2 * len(Gc_rewired.nodes))
    return Gc_rewired


# def rewire_network():


# TODO add option to save the rewire results
def simulate_rewire(Gc, rewired=False, rewire_df_name=None, arr_name=None, **kwargs):
    """This function reads rewired network GNM data or calls rewire function

    :param Gc: network to be rewired
    :type Gc: networkx object
    :param rewired: Is there a rewired GNM data available, defaults to False
    :type rewired: bool, optional
    :param rewire_df_name: If rewired is True, related dataframe path should be given, defaults to None
    :type rewire_df_name: string, optional
    :param arr_name: If rewired is True, related numpy array txt file path should be given, defaults to None
    :type arr_name: string, optional
    :raises ValueError: If rewired is True and rewire_df_name or arr_name is not given, raises error
    :return: arr
    :rtype: numpy array
    :return: rewire_df
    :rtype: pandas dataframe    
    """
    from scipy.stats import pearsonr, spearmanr
    from tqdm import tqdm
    save = kwargs.pop('save', False)
    output_name = kwargs.pop('output_name', 'rewire_data')
    output_path = kwargs.pop('output_path', '../data/interim/') 
    if rewired:
        # rewire_df_name = kwargs.pop('rewire_df_name',None)
        # arr_name = kwargs.pop('arr_name',None)
        if rewire_df_name is None or arr_name is None:
            raise ValueError(
                'Rewired dataframe path or arr_name is not given ')
        rewire_df = pd.read_csv(rewire_df_name)
        arr = np.load(arr_name)
    else:

        sim_num = kwargs.pop('sim_num', 10)
        arr = np.zeros((len(Gc.nodes), len(Gc.nodes), int(sim_num)))
        # pearsonr(eff,degree)[0]
        rewire_df = pd.DataFrame(columns=['eff_deg_pearson', 'sens_deg_pearson', 'eff_deg_spearman', 'sens_deg_spearman',
                                          'eff_btw_pearson', 'sens_btw_pearson', 'eff_btw_spearman', 'sens_btw_spearman',
                                          'eff_trans_pearson', 'sens_trans_pearson', 'eff_trans_spearman',
                                          'sens_trans_spearman'])
        e_list = []
#        for i in tqdm(range(int(sim_num))):
        success = 0
        i=0
        maxtry=100
        while success<(sim_num) or i==maxtry:
            print(i)
            i=i+1
            try:
                Gc_rew = rewire_network(Gc, **kwargs)
#                print(Gc_rew)
                enm_rew = Enm('rewired')

                
                enm_rew.G = Gc_rew
                enm_rew.giant_component()
#                print(enm_rew.graph_gc)
                enm_rew.gnm_analysis(**kwargs)
                res = enm_rew.prs_mat
#                print(res)
                #Gc_rew = enm_rew.graph_gc
                degree = enm_rew.degree
                e_list.append(enm_rew)
                success = success+1
                #i=i+1
            except Exception as e:
                print('error')
                continue

            arr[:, :, (success-1)] = res
            eff_rew = enm_rew.df.eff.values
            sens_rew = enm_rew.df.sens.values
            # eff_hist_list.append(eff_rew)
            # sens_hist_list.append(eff_rew)
            # betweenness_nx(Gc_rew, normalized=True)
            betweenness = enm_rew.df.btw.values
            clustering_coeff = enm_rew.df.trans.values
            rewire_df_itr = pd.DataFrame([[pearsonr(eff_rew, degree)[0], pearsonr(sens_rew, degree)[0],
                                           spearmanr(eff_rew, degree)[0], spearmanr(
                                               sens_rew, degree)[0],
                                           pearsonr(eff_rew, betweenness)[0], pearsonr(
                                               sens_rew, betweenness)[0],
                                           spearmanr(eff_rew, betweenness)[0], spearmanr(
                                               sens_rew, betweenness)[0],
                                           pearsonr(eff_rew, clustering_coeff)[0], pearsonr(
                                               sens_rew, clustering_coeff)[0],
                                           spearmanr(
                                               eff_rew, clustering_coeff)[0],
                                           spearmanr(sens_rew, clustering_coeff)[0]]],
                                         columns=['eff_deg_pearson', 'sens_deg_pearson', 'eff_deg_spearman',
                                                  'sens_deg_spearman',
                                                  'eff_btw_pearson', 'sens_btw_pearson', 'eff_btw_spearman',
                                                  'sens_btw_spearman',
                                                  'eff_trans_pearson', 'sens_trans_pearson', 'eff_trans_spearman',
                                                  'sens_trans_spearman'])
            rewire_df = rewire_df.append(rewire_df_itr)
            # if i % 1 == 0:
            #     print(i)
        # rewire_df.to_csv(outpath+'/rewire_df.csv')

        if save:
            rewire_df.to_csv(f"{output_path}/{output_name}.csv")
            np.save(f"{output_path}/{output_name}.npy", arr)
            with open(f"{output_path}/{output_name}.pickle", 'wb') as handle:
                pickle.dump(e_list, handle)
    return arr, rewire_df, e_list
