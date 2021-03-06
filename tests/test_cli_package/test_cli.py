import pytest

import shutil
from pathlib import Path
from click.testing import CliRunner

from bnmutils import ConfigParser
from bnmutils.novelty import cd

from logme.exceptions import LogmeError
from logme.utils import get_logger_config
from logme import __version__

from logme import cli


class TestCli:

    @classmethod
    def setup_class(cls):
        cls.runner = CliRunner()

    def test_version(self):
        result = self.runner.invoke(cli, ['-v'])
        assert f"version {__version__}" in result.output

    # ---------------------------------------------------------------------------
    # 'logme init' test
    # ---------------------------------------------------------------------------
    @pytest.mark.parametrize('file_path, cmd_args',
                             [pytest.param('logme.ini', ['init'],
                                           id='init from root dir'),
                              pytest.param('dir2/logme.ini', ['init', '-p', 'dir2', '-mk'],
                                           id='init with an additional dir -relative path')])
    def test_init(self, tmpdir, file_path, cmd_args):

        expected_file = Path(tmpdir.join(file_path))

        with cd(tmpdir):
            result = self.runner.invoke(cli, cmd_args)

            assert result.exit_code == 0
            assert expected_file.is_file()

            conf = ConfigParser.from_files(expected_file)
            assert conf.sections() == ['colors', 'logme']

            # Assert the first section is the color config
            with open(expected_file) as file:
                line = file.readline()
                assert line == '[colors]\n'

    def test_init_absolute_root_path(self, tmpdir):

        root_path = Path(tmpdir.join('dir_abs'))

        with cd(tmpdir):
            result = self.runner.invoke(cli, ['init', '-p', str(root_path), '-mk'])

            assert result.exit_code == 0
            assert (root_path / 'logme.ini').is_file()

    @pytest.mark.parametrize('option, key, expected',
                             [pytest.param(['-lvl', 'INFO'], ['logme', 'level'], 'INFO',
                                           id='with custom level'),
                              pytest.param(['-lvl', 'error'], ['logme', 'level'], 'ERROR',
                                           id='with custom level as lower case string'),
                              pytest.param(['-lvl', '50'], ['logme', 'level'], '50',
                                           id='with custom level as integer'),
                              pytest.param(['-f', '{name} : {message}'], ['logme', 'formatter'],
                                           '{name} : {message}',
                                           id='with custom formatter'),
                              ])
    def test_init_file_change(self, tmpdir, option, key, expected):

        self.runner.invoke(cli, ['init', '-p', tmpdir] + option)

        conf = ConfigParser.from_files(tmpdir.join('logme.ini'))

        assert conf.get(*key) == expected

    def test_init_chained_options(self, tmpdir):

        tmp = tmpdir.join('my_project')
        
        self.runner.invoke(cli, ['init', '-p', tmp,
                                 '-mk', '-lp', tmp.join('var/log/dummy.log')])

        config = ConfigParser.from_files(tmp.join('logme.ini'))

        fh_conf = config.to_dict(section='logme', option='file')

        assert fh_conf['filename'] == tmp.join('var/log/dummy.log')
        assert set(fh_conf.keys()) == {'active', 'level', 'filename', 'type'}

    def test_init_raise_invalid_dir(self, tmpdir):

        with cd(tmpdir):
            result = self.runner.invoke(cli, ['init', '-p', 'blah'])

            with pytest.raises(NotADirectoryError) as e_info:
                raise result.exception

            assert e_info.value.args[0] == f"{tmpdir.join('blah')} does not exist. If you'd " \
                                           f"like to make the directory, please use '-mk' flag."

    def test_init_raise_conf_exists(self, tmpdir):

        with cd(tmpdir):
            self.runner.invoke(cli, ['init'])
            logme_path = Path(tmpdir) / 'logme.ini'
            assert logme_path.exists()

            result = self.runner.invoke(cli, ['init'])

            with pytest.raises(LogmeError) as e_info:
                raise result.exception

            assert e_info.value.args[0] == f"logme.ini already exists at {logme_path}"

    def test_init_override(self, tmpdir):

        with cd(tmpdir):
            # Before override
            self.runner.invoke(cli, ['init', '-lvl', 'error'])
            logme_path = Path(tmpdir) / 'logme.ini'

            conf_content_before = get_logger_config(logme_path)
            assert conf_content_before['level'] == 'ERROR'

            self.runner.invoke(cli, ['init', '-o'])
            conf_content_after = get_logger_config(logme_path)
            assert conf_content_after['level'] == 'DEBUG'

    # ---------------------------------------------------------------------------
    # 'logme add' test
    # ---------------------------------------------------------------------------
    def test_add_command(self, tmpdir):

        with cd(tmpdir):
            self.runner.invoke(cli, ['init'])
            result = self.runner.invoke(cli, ['add', 'blah'])

            config_path = tmpdir.join('logme.ini')
            config = ConfigParser.from_files(config_path)

            assert result.exit_code == 0
            assert Path(config_path).is_file()

            assert set(config.sections()) == {'colors', 'logme', 'blah'}

    def test_add_command_no_file(self, tmpdir):

        with cd(tmpdir):
            with pytest.raises(FileNotFoundError):
                result = self.runner.invoke(cli, ['add', 'blah'])
                raise result.exception

    # ---------------------------------------------------------------------------
    # 'logme remove' test
    # ---------------------------------------------------------------------------

    def test_remove_command(self, tmpdir):

        with cd(tmpdir):
            self.runner.invoke(cli, ['init'])
            self.runner.invoke(cli, ['add', 'test'])

            config_path = tmpdir.join('logme.ini')
            config_before = ConfigParser.from_files(config_path)

            assert set(config_before.sections()) == {'colors', 'logme', 'test'}

            result = self.runner.invoke(cli, ['remove', 'test'])
            config_after = ConfigParser.from_files(config_path)

            assert result.exit_code == 0
            assert config_after.sections() == ['colors', 'logme']

    @pytest.mark.parametrize('conf_name, message',
                             [
                                 pytest.param('logme', "'logme' master configuration cannot be removed!",
                                              id='when trying to remove logme master config'),
                                 pytest.param('colors', "'colors' configuration cannot be removed! To remove "
                                                       "color logging, set all color values to 'None'",
                                              id='when trying to remove color config')
                             ])
    def test_remove_raise(self, tmpdir, conf_name, message):

        with cd(tmpdir):
            self.runner.invoke(cli, ['init'])

            with pytest.raises(LogmeError) as e_info:
                result = self.runner.invoke(cli, ['remove', conf_name])
                raise result.exception

            assert e_info.value.args[0] == message

    # ---------------------------------------------------------------------------
    # 'logme upgrade' test
    # ---------------------------------------------------------------------------
    def test_upgrade_command(self, tmpdir):
        local_logme_file = Path(__file__).parent / 'logme.ini'
        tmpdir_file = tmpdir.join('logme.ini')

        shutil.copyfile(local_logme_file, tmpdir_file)

        with cd(tmpdir):
            result = self.runner.invoke(cli, ['upgrade'])

            assert result.output.strip() == f"{tmpdir_file} has been updated to {__version__}"
