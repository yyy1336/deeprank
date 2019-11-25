import warnings

import pdb2sql

from deeprank.features import FeatureClass

try:
    import freesasa

except ImportError:
    warnings.warn('freesasa module not found')
    raise


class BSA(FeatureClass):

    def __init__(self, pdb_data, chainA='A', chainB='B'):
        """Compute the burried surface area feature.

        Freesasa is required for this feature.
        From Freesasa version 2.0.3 the Python bindings are released
        as a separate module. They can be installed using
        >>> pip install freesasa

        Args :
            pdb_data (list(byte) or str): pdb data or pdb filename
            chainA (str, optional): name of the first chain
            chainB (str, optional): name of the second chain

        Example :
        >>> bsa = BSA('1AK4.pdb')
        >>> bsa.get_structure()
        >>> bsa.get_contact_residue_sasa()
        >>> bsa.sql.close()
        """
        self.pdb_data = pdb_data
        self.sql = pdb2sql.interface(pdb_data)
        self.chains_label = [chainA, chainB]

        self.feature_data = {}
        self.feature_data_xyz = {}

        freesasa.setVerbosity(freesasa.nowarnings)

    def get_structure(self):
        """Get the pdb structure of the molecule."""

        # we can have a str or a list of bytes as input
        if isinstance(self.pdb_data, str):
            self.complex = freesasa.Structure(self.pdb_data)
        else:
            self.complex = freesasa.Structure()
            atomdata = self.sql.get('name,resName,resSeq,chainID,x,y,z')
            for atomName, residueName, residueNumber, chainLabel, x, y, z \
                    in atomdata:
                atomName = '{:>2}'.format(atomName[0])
                self.complex.addAtom(atomName, residueName,
                                     residueNumber, chainLabel, x, y, z)
        self.result_complex = freesasa.calc(self.complex)

        self.chains = {}
        self.result_chains = {}
        for label in self.chains_label:
            self.chains[label] = freesasa.Structure()
            atomdata = self.sql.get(
                'name,resName,resSeq,chainID,x,y,z', chainID=label)
            for atomName, residueName, residueNumber, chainLabel, x, y, z \
                    in atomdata:
                atomName = '{:>2}'.format(atomName[0])
                self.chains[label].addAtom(
                    atomName, residueName, residueNumber, chainLabel, x, y, z)
            self.result_chains[label] = freesasa.calc(self.chains[label])

    def get_contact_residue_sasa(self, cutoff=5.5):
        """Compute the feature of BSA.

            It generates following feature:
                bsa

        Raises:
            ValueError: No interface residues found.
        """

        self.bsa_data = {}
        self.bsa_data_xyz = {}

        ctc_res = self.sql.get_contact_residues(cutoff=cutoff)
        ctc_res = ctc_res["A"] + ctc_res["B"]

        # handle with small interface or no interface
        total_res = len(ctc_res)
        if total_res == 0:
            raise ValueError(
                f"No interface residue found with the cutoff {cutoff}Å."
                f" Failed to calculate the feature BSA")
        elif total_res < 5:  # this is an empirical value
            warnings.warn(
                f"Only {total_res} interface residues found with cutoff"
                f" {cutoff}Å. Be careful with using the feature BSA")

        for res in ctc_res:

            # define the selection string and the bsa for the complex
            select_str = ('res, (resi %d) and (chain %s)' % (res[1], res[0]),)
            asa_complex = freesasa.selectArea(
                select_str, self.complex, self.result_complex)['res']

            # define the selection string and the bsa for the isolated
            select_str = ('res, resi %d' % res[1],)
            asa_unbound = freesasa.selectArea(
                select_str, self.chains[res[0]],
                self.result_chains[res[0]])['res']

            # define the bsa
            bsa = asa_unbound - asa_complex

            # define the xyz key : (chain,x,y,z)
            chain = {'A': 0, 'B': 1}[res[0]]

            atcenter = 'CB'
            if res[2] == 'GLY':
                atcenter = 'CA'
            xyz = self.sql.get(
                'x,y,z', resSeq=res[1], chainID=res[0], name=atcenter)[0]
            # xyz = np.mean(self.sql.get('x,y,z',resSeq=r[1],chainID=r[0]),0)
            xyzkey = tuple([chain] + xyz)

            # put the data in dict
            self.bsa_data[res] = [bsa]
            self.bsa_data_xyz[xyzkey] = [bsa]

        # pyt the data in dict
        self.feature_data['bsa'] = self.bsa_data
        self.feature_data_xyz['bsa'] = self.bsa_data_xyz

########################################################################
#
#   THE MAIN FUNCTION CALLED IN THE INTERNAL FEATURE CALCULATOR
#
########################################################################


def __compute_feature__(pdb_data, featgrp, featgrp_raw):

    # create the BSA instance
    bsa = BSA(pdb_data)

    # get the structure/calc
    bsa.get_structure()

    # get the feature info
    bsa.get_contact_residue_sasa()

    # export in the hdf5 file
    bsa.export_dataxyz_hdf5(featgrp)
    bsa.export_data_hdf5(featgrp_raw)

    # close the file
    bsa.sql.close()


########################################################################
#
#       TEST THE CLASS
#
########################################################################

if __name__ == '__main__':

    import os
    from pprint import pprint
    # get base path */deeprank, i.e. the path of deeprank package
    base_path = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.realpath(__file__))))
    pdb_file = os.path.join(base_path, "test/1AK4/native/1AK4.pdb")

    bsa = BSA(pdb_file)
    bsa.get_structure()
    bsa.get_contact_residue_sasa()
    bsa.sql.close()

    pprint(bsa.feature_data)
    print()
    pprint(bsa.feature_data_xyz)
